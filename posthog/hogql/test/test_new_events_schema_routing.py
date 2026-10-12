from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    ActorsQuery,
    EventsNode,
    ExperimentExposureQuery,
    ExperimentMeanMetric,
    ExperimentQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationResultsType,
    FunnelsActorsQuery,
    FunnelsQuery,
    HogQLQuery,
    HogQLQueryModifiers,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    PersonsOnEventsMode,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Organization, Team, User

from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
class TestNewEventsClusterRouting(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=44, modifiers={}, organization=Organization(id=1))
        self.user = User(id=123, is_staff=True, is_active=True)
        self.modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        self.settings_patch = patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: [44] if key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        cookieless = patch(
            "products.web_analytics.backend.hogql_queries.cookieless_flag.resolve_cookieless_traffic_is_regular_modifier",
            return_value=True,
        )
        cookieless.start()
        self.addCleanup(cookieless.stop)

    def test_explicit_false_is_the_comparison_and_rollback_control(self) -> None:
        self.modifiers.useNewEventsSchema = False
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    @parameterized.expand([([],), ([True],), (["44"],), ("44",), ({"44": True},)])
    def test_missing_or_malformed_eligibility_rejects_cluster_opt_in(self, allowed: object) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        with patch("posthog.models.event.new_events_schema.get_instance_setting", return_value=allowed):
            with self.assertRaisesRegex(ExposedHogQLError, "not enabled"):
                HogQLQueryRunner(
                    query=HogQLQuery(
                        query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True})
                    ),
                    team=self.team,
                )

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=None)
    def test_missing_host_rejects_opt_in_before_cache(self) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        with self.assertRaisesRegex(ExposedHogQLError, "host is not configured"):
            HogQLQueryRunner(
                query=HogQLQuery(
                    query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True})
                ),
                team=self.team,
            )

    def test_project_defaults_cannot_opt_in_and_settings_api_drops_cluster_choice(self) -> None:
        from posthog.api.team import TeamSerializer

        self.team.modifiers = {"useNewEventsCluster": True, "useNewEventsSchema": True}
        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team)
        self.assertIsNone(runner.modifiers.useNewEventsCluster)
        self.assertIs(runner.modifiers.useNewEventsSchema, True)
        self.assertEqual(
            TeamSerializer.validate_modifiers(
                {"useNewEventsCluster": True, "useNewEventsSchema": True, "personsOnEventsMode": "disabled"}
            ),
            {"personsOnEventsMode": "disabled"},
        )

    def test_worker_revalidates_eligibility_instead_of_falling_back(self) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}))
        runner = HogQLQueryRunner(query=source, team=self.team)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(cache_manager=cache, user=self.user)
        with patch("posthog.models.event.new_events_schema.get_instance_setting", return_value=[]):
            with self.assertRaisesRegex(ExposedHogQLError, "not enabled"):
                get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=self.user)

    def test_direct_warehouse_connection_cannot_claim_native_cluster_opt_in(self) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        with self.assertRaisesRegex(ExposedHogQLError, "warehouse connection"):
            HogQLQueryExecutor(
                query="SELECT 1",
                team=self.team,
                modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}),
                connection_id="example-connection",
            )

    @parameterized.expand(
        [(kind, choice) for kind in ("HogQLQuery", "InsightActorsQuery", "ActorsQuery") for choice in (False, None)]
    )
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=None)
    def test_cluster_only_constructor_override_survives_conflicting_raw_opt_in(
        self, kind: str, choice: bool | None
    ) -> None:
        query = (
            HogQLQuery(query="SELECT 1", modifiers=self.modifiers) if kind == "HogQLQuery" else self._nested_query(kind)
        )
        assert isinstance(query, (HogQLQuery, InsightActorsQuery, ActorsQuery))
        query.modifiers = self.modifiers.model_copy(update={"useNewEventsCluster": True})
        runner = get_query_runner(
            query,
            self.team,
            modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": choice}),
            user=self.user,
        )
        original = query.model_dump()
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(cache_manager=cache, user=self.user)
        worker = get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=self.user)
        self.assertIs(worker.modifiers.useNewEventsCluster, choice)
        self.assertIs(worker.modifiers.useNewEventsSchema, False)
        self.assertEqual(query.model_dump(), original)

    @parameterized.expand([(False,), (True,)])
    def test_authenticated_query_pins_existing_schema_default_before_cache(self, native: bool) -> None:
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: native if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA" else False,
        ):
            runner = HogQLQueryRunner(
                query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
            )
        self.assertIs(runner.modifiers.useNewEventsSchema, native)
        self.assertIsNone(runner.modifiers.useNewEventsCluster)

    def test_cluster_opt_in_resolves_table_before_cache_lookup(self) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True})
            ),
            team=self.team,
            user=self.user,
        )
        self.assertIs(runner.modifiers.useNewEventsSchema, True)

    def test_async_query_serializes_effective_table_without_changing_saved_source(self) -> None:
        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}))
        runner = HogQLQueryRunner(query=source, team=self.team, user=self.user)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(cache_manager=cache, user=self.user)
        self.assertIs(enqueue.call_args.kwargs["query_json"]["modifiers"]["useNewEventsSchema"], True)
        assert source.modifiers is not None
        self.assertIsNone(source.modifiers.useNewEventsSchema)

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=None)
    def test_unconfigured_route_preserves_legacy_async_payload_for_older_workers(self) -> None:
        ordinary = User(id=124, is_staff=True, is_active=True)
        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers)
        runner = HogQLQueryRunner(query=source, team=self.team, user=ordinary)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(cache_manager=cache, user=ordinary)
        self.assertEqual(enqueue.call_args.kwargs["query_json"], source.model_dump())

    def test_async_effective_modifier_has_same_cache_payload_as_request(self) -> None:
        request = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True})
            ),
            team=self.team,
            user=self.user,
        )
        effective = self.modifiers.model_copy(update={"useNewEventsSchema": True, "useNewEventsCluster": True})
        worker = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=effective), team=self.team, user=self.user
        )
        with (
            patch.object(request, "_get_property_access_restrictions", return_value=None),
            patch.object(worker, "_get_property_access_restrictions", return_value=None),
            patch.object(request, "_products_modifiers_for_cache", return_value={}),
            patch.object(worker, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            self.assertEqual(request.get_cache_payload(), worker.get_cache_payload())

    def _nested_query(self, kind: str, native: bool | None = None) -> BaseModel:
        modifiers = self.modifiers.model_copy(update={"useNewEventsSchema": native, "useNewEventsCluster": native})
        trends = TrendsQuery(series=[EventsNode(event="example")], modifiers=modifiers)
        actors = InsightActorsQuery(source=trends)
        if kind == "ActorsQuery":
            return ActorsQuery(source=actors)
        if kind == "InsightActorsQueryOptions":
            return InsightActorsQueryOptions(source=actors)
        if kind == "FunnelCorrelationQuery":
            return FunnelCorrelationQuery(
                funnelCorrelationType=FunnelCorrelationResultsType.EVENTS,
                source=FunnelsActorsQuery(
                    funnelStep=1,
                    source=FunnelsQuery(
                        series=[EventsNode(event="example"), EventsNode(event="finished")], modifiers=modifiers
                    ),
                ),
            )
        return actors

    @parameterized.expand(
        [("InsightActorsQuery",), ("InsightActorsQueryOptions",), ("ActorsQuery",), ("FunnelCorrelationQuery",)]
    )
    def test_nested_async_choice_survives_worker_reconstruction_and_preserves_cache_identity(self, kind: str) -> None:
        query = self._nested_query(kind, True)
        original = query.model_dump()
        request = get_query_runner(query, self.team, user=self.user)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            request.enqueue_async_calculation(cache_manager=cache, user=self.user)
        worker = get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=self.user)
        self.assertIs(worker.modifiers.useNewEventsCluster, True)
        self.assertIs(worker.modifiers.useNewEventsSchema, True)
        self.assertEqual(query.model_dump(), original)
        with (
            patch.object(request, "_get_property_access_restrictions", return_value=None),
            patch.object(worker, "_get_property_access_restrictions", return_value=None),
            patch.object(request, "_products_modifiers_for_cache", return_value={}),
            patch.object(worker, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            self.assertEqual(request.get_cache_payload(), worker.get_cache_payload())

    @parameterized.expand([(False,), (True,)])
    def test_actor_source_explicit_choice_survives_late_user(self, native: bool) -> None:
        runner = get_query_runner(self._nested_query("ActorsQuery", native), self.team)
        with patch.object(runner, "get_cache_key", side_effect=RuntimeError("cache boundary")):
            with self.assertRaisesRegex(RuntimeError, "cache boundary"):
                runner.run(user=self.user)
        self.assertIs(runner.modifiers.useNewEventsSchema, native)

    @parameterized.expand(
        [("InsightActorsQuery", False), ("InsightActorsQuery", True), ("ActorsQuery", False), ("ActorsQuery", True)]
    )
    def test_async_constructor_override_beats_conflicting_wrapper_after_worker_reconstruction(
        self, kind: str, native: bool
    ) -> None:
        query = self._nested_query(kind)
        assert isinstance(query, (ActorsQuery, InsightActorsQuery))
        query.modifiers = self.modifiers.model_copy(
            update={"useNewEventsSchema": not native, "useNewEventsCluster": not native}
        )
        original = query.model_dump()
        with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com" if native else None):
            runner = get_query_runner(
                query,
                self.team,
                modifiers=self.modifiers.model_copy(
                    update={"useNewEventsSchema": native, "useNewEventsCluster": native}
                ),
                user=self.user,
            )
            cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
            with (
                patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
                patch("posthog.hogql_queries.query_runner.groups", return_value={}),
                patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
            ):
                runner.enqueue_async_calculation(cache_manager=cache, user=self.user)
            worker = get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=self.user)
        self.assertIs(worker.modifiers.useNewEventsSchema, native)
        self.assertEqual(query.model_dump(), original)

    @parameterized.expand([(False,), (True,)])
    def test_native_cache_identity_tracks_host_configuration_without_changing_legacy_namespace(
        self, native: bool
    ) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT 1",
                modifiers=self.modifiers.model_copy(
                    update={"useNewEventsSchema": native, "useNewEventsCluster": native}
                ),
            ),
            team=self.team,
        )
        with (
            patch.object(runner, "_get_property_access_restrictions", return_value=None),
            patch.object(runner, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            keys = []
            for host in ("native.example.com", "replacement.example.com"):
                with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=host):
                    keys.append(runner.get_cache_key())
        self.assertEqual(len(set(keys)), 2 if native else 1)

    @parameterized.expand([("HogQLQuery",), ("InsightActorsQuery",), ("ActorsQuery",)])
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=None)
    def test_async_constructor_false_survives_without_a_raw_schema_choice(self, kind: str) -> None:
        query = (
            HogQLQuery(query="SELECT 1", modifiers=self.modifiers) if kind == "HogQLQuery" else self._nested_query(kind)
        )
        original = query.model_dump()
        runner = get_query_runner(
            query, self.team, modifiers=self.modifiers.model_copy(update={"useNewEventsSchema": False}), user=self.user
        )
        self.assertIs(runner.modifiers.useNewEventsSchema, False)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(cache_manager=cache, user=self.user)
        worker = get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=self.user)
        self.assertIs(worker.modifiers.useNewEventsSchema, False)
        self.assertEqual(query.model_dump(), original)

    @parameterized.expand([(False,), (True,)])
    def test_explicit_wrapper_choices_take_precedence_over_source(self, native: bool) -> None:
        query = self._nested_query("ActorsQuery", not native)
        assert isinstance(query, ActorsQuery)
        query.modifiers = self.modifiers.model_copy(
            update={"useNewEventsSchema": native, "useNewEventsCluster": native}
        )
        runner = get_query_runner(query, self.team, user=self.user)
        assert isinstance(runner, ActorsQueryRunner)
        with patch.object(runner, "get_cache_key", side_effect=RuntimeError("cache boundary")):
            with self.assertRaisesRegex(RuntimeError, "cache boundary"):
                runner.run(user=self.user)
        self.assertIs(runner.modifiers.useNewEventsSchema, native)
        assert runner.source_query_runner is not None
        self.assertIs(runner.source_query_runner.modifiers.useNewEventsSchema, native)

    def test_legacy_default_retains_cache_namespace_when_choice_is_resolved(self) -> None:
        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team)
        with (
            patch.object(runner, "_get_property_access_restrictions", return_value=None),
            patch.object(runner, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            payload = runner.get_cache_payload()
        self.assertIs(runner.modifiers.useNewEventsSchema, False)
        self.assertNotIn("useNewEventsSchema", payload["hogql_modifiers"])

    def test_direct_hogql_execution_resolves_the_same_cluster_opt_in(self) -> None:
        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            user=self.user,
            modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}),
        )
        self.assertIs(executor.query_modifiers.useNewEventsSchema, True)

    @parameterized.expand([(False,), (True,)])
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_direct_trino_queue_preserves_pure_inputs(self, enrolled: bool) -> None:
        from posthog.hogql.transforms.trino.manifest import TrinoCatalogManifest, transpile_hogql_to_trino

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.DISABLED}
        query = HogQLQuery(query="SELECT 1", connectionId="example-connection")
        user = self.user if enrolled else User(id=124, is_staff=True)
        source = MagicMock(direct_engine="trino", has_managed_warehouse_prefix=False)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.hogql_query_runner.get_direct_connection_source", return_value=source),
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner = HogQLQueryRunner(query=query, team=self.team, user=user)
            runner.enqueue_async_calculation(cache_manager=cache, user=user)
            worker = get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=user)
        assert isinstance(worker, HogQLQueryRunner)
        compiled = transpile_hogql_to_trino(
            worker.query.query,
            manifest=TrinoCatalogManifest(tables=()),
            filters=worker.query.filters,
            variables=worker.query.variables,
            modifiers=worker.query.modifiers,
        )
        self.assertIn("SELECT 1", compiled.sql)
        self.assertEqual(enqueue.call_args.kwargs["query_json"], query.model_dump())

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_cluster_opt_in_executes_on_native_workload(self) -> None:
        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            user=self.user,
            modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}),
        )
        executor.clickhouse_sql = "SELECT 1"
        executor.clickhouse_context = HogQLContext(
            team_id=self.team.pk, modifiers=HogQLQueryModifiers(useNewEventsSchema=True)
        )
        executor.select_query = ast.SelectQuery(select=[ast.Constant(value=1)])
        with (
            patch.object(executor, "_plan_fingerprint", return_value="example"),
            patch.object(executor, "_detect_warehouse_sources"),
            patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
        ):
            executor._execute_clickhouse_query()
        self.assertEqual(execute.call_args.kwargs["workload"].value, "NATIVE_EVENTS")

    @parameterized.expand(
        [
            (None, True, Workload.DEFAULT),
            ("native.example.com", False, Workload.DEFAULT),
            ("native.example.com", True, Workload.LOGS),
        ]
    )
    def test_unconfigured_legacy_and_logs_queries_keep_existing_route(
        self, host: str | None, native: bool, workload: Workload
    ) -> None:
        with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=host):
            executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, modifiers=self.modifiers, workload=workload)
            executor.clickhouse_sql = "SELECT 1"
            executor.clickhouse_context = HogQLContext(
                team_id=self.team.pk, modifiers=HogQLQueryModifiers(useNewEventsSchema=native)
            )
            executor.select_query = ast.SelectQuery(select=[ast.Constant(value=1)])
            with (
                patch.object(executor, "_plan_fingerprint", return_value="example"),
                patch.object(executor, "_detect_warehouse_sources"),
                patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
            ):
                executor._execute_clickhouse_query()
            self.assertEqual(execute.call_args.kwargs["workload"], workload)


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
class TestNativeEventsExplicitQueryRouting(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        settings_patch = patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: [self.team.id] if key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False,
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    @parameterized.expand([("metric", False), ("metric", True), ("exposures", False), ("exposures", True)])
    def test_experiment_execution_preserves_selected_table_and_debug_sql(self, kind: str, native: bool) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="example-experiment",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="Example experiment",
            feature_flag=flag,
            start_date=datetime(2024, 1, 1, tzinfo=UTC),
            end_date=datetime(2024, 1, 7, tzinfo=UTC),
        )
        assert experiment.start_date is not None and experiment.end_date is not None
        modifiers = HogQLQueryModifiers(useNewEventsSchema=native, useNewEventsCluster=native)
        runner: ExperimentQueryRunner | ExperimentExposuresQueryRunner
        if kind == "metric":
            runner = ExperimentQueryRunner(
                query=ExperimentQuery(
                    experiment_id=experiment.id, metric=ExperimentMeanMetric(source=EventsNode(event="example"))
                ),
                team=self.team,
                user=self.user,
                modifiers=modifiers,
            )
            builder = "_get_experiment_query"
        else:
            runner = ExperimentExposuresQueryRunner(
                query=ExperimentExposureQuery(
                    experiment_id=experiment.id,
                    experiment_name=experiment.name,
                    feature_flag={"key": flag.key},
                    start_date=experiment.start_date.isoformat(),
                    end_date=experiment.end_date.isoformat(),
                ),
                team=self.team,
                user=self.user,
                modifiers=modifiers,
            )
            builder = "_get_exposure_query"
        cache_key = runner.get_cache_key()
        with (
            patch.object(runner, builder, return_value=parse_select("SELECT count() FROM events")),
            patch("posthog.hogql.query.sync_execute", return_value=([], [("count()", "UInt64")])) as execute,
        ):
            if kind == "metric":
                assert isinstance(runner, ExperimentQueryRunner)
                runner._evaluate_experiment_query()
            else:
                assert isinstance(runner, ExperimentExposuresQueryRunner)
                runner._calculate()
        self.assertEqual("events_json" in execute.call_args.args[0], native)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NATIVE_EVENTS, native)
        self.assertEqual(runner.get_cache_key(), cache_key)
        if kind == "metric":
            assert isinstance(runner, ExperimentQueryRunner)
            assert runner.clickhouse_sql is not None
            self.assertEqual("events_json" in runner.clickhouse_sql, native)


@override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestNewEventsClusterPilot(APIBaseTest):
    def _run_sql(self, modifiers: dict[str, bool]):
        return self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {
                "query": {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events", "modifiers": modifiers},
                "refresh": "force_blocking",
            },
            format="json",
        )

    @parameterized.expand([(True,), (False,)])
    def test_cluster_opt_in_checks_project_eligibility(self, eligible: bool) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: (
                    [self.team.id] if eligible and key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False
                ),
            ),
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
        ):
            response = self._run_sql({"useNewEventsCluster": True})
        self.assertEqual(response.status_code, 200 if eligible else 400, response.json())
        if eligible:
            self.assertEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)
            self.assertIn("events_json", execute.call_args.args[0])
            self.assertIs(response.json()["modifiers"]["useNewEventsCluster"], True)
        else:
            execute.assert_not_called()

    @parameterized.expand(
        [
            ({}, False),
            ({"useNewEventsSchema": True}, True),
            ({"useNewEventsCluster": False, "useNewEventsSchema": True}, True),
        ]
    )
    def test_existing_query_choices_keep_their_connection(self, modifiers: dict[str, bool], native_table: bool) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: [self.team.id] if key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False,
            ),
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
        ):
            response = self._run_sql(modifiers)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertNotEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)
        self.assertEqual("events_json" in execute.call_args.args[0], native_table)

    def test_staff_can_enable_and_disable_pilot_eligibility_through_api(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        endpoint = "/api/instance_settings/CLICKHOUSE_NATIVE_EVENTS_TEAMS"
        for value in ([self.team.id], []):
            response = self.client.patch(endpoint, {"value": value}, format="json")
            self.assertEqual(response.status_code, 200, response.json())
            self.assertEqual(response.json()["value"], value)
            with patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute:
                query_response = self._run_sql({"useNewEventsCluster": True})
            self.assertEqual(query_response.status_code, 200 if value else 400, query_response.json())
            self.assertEqual(execute.called, bool(value))

    def test_nonstaff_cannot_enable_pilot_eligibility(self) -> None:
        response = self.client.patch(
            "/api/instance_settings/CLICKHOUSE_NATIVE_EVENTS_TEAMS", {"value": [self.team.id]}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.json())
