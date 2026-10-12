import json
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
from products.product_analytics.backend.facade.queries import FunnelCorrelationQueryRunner


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestNewEventsSchemaUserRollout(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=44, modifiers={}, organization=Organization(id=1))
        self.user = User(id=123, is_staff=True, is_active=True)
        self.modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        self.settings_patch = patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: '{"44": [123]}' if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        cookieless = patch(
            "products.web_analytics.backend.hogql_queries.cookieless_flag.resolve_cookieless_traffic_is_regular_modifier",
            return_value=True,
        )
        cookieless.start()
        self.addCleanup(cookieless.stop)

    def test_staff_opt_in_changes_only_that_users_project_default(self) -> None:
        selected = create_default_modifiers_for_user(self.user, self.team, self.modifiers)
        self.assertIs(selected.useNewEventsSchema, True)
        self.assertIsNone(self.modifiers.useNewEventsSchema)
        self.assertIs(
            create_default_modifiers_for_user(
                User(id=124, is_staff=True), self.team, self.modifiers
            ).useNewEventsSchema,
            False,
        )
        self.assertIs(
            create_default_modifiers_for_user(self.user, Team(id=45), self.modifiers).useNewEventsSchema, False
        )

    @parameterized.expand([(False, True), (True, False)])
    def test_nonstaff_and_inactive_users_cannot_inherit_opt_in(self, staff: bool, active: bool) -> None:
        self.user.is_staff, self.user.is_active = staff, active
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    def test_explicit_false_is_the_comparison_and_rollback_control(self) -> None:
        self.modifiers.useNewEventsSchema = False
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    def test_team_false_overrides_user_default(self) -> None:
        self.team.modifiers = {"useNewEventsSchema": False}
        self.assertIs(create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False)

    @parameterized.expand([("not json",), ('{"44": true}',), ('{"44": ["123"]}',), ('{"44": [true]}',)])
    def test_malformed_enrollment_fails_closed(self, enrollment: str) -> None:
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: enrollment if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
        ):
            self.assertIs(
                create_default_modifiers_for_user(self.user, self.team, self.modifiers).useNewEventsSchema, False
            )

    def test_query_runner_resolves_user_default_before_cache_lookup(self) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
        )
        self.assertIs(runner.modifiers.useNewEventsSchema, True)

    def test_changing_query_actor_resets_only_the_inherited_table_choice(self) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
        )
        self.assertIs(runner.modifiers.useNewEventsSchema, True)
        runner.user = User(id=124, is_staff=True)
        runner._on_user_changed()
        self.assertIs(runner.modifiers.useNewEventsSchema, False)

    def test_user_supplied_at_run_is_resolved_before_cache_lookup(self) -> None:
        runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team)
        with patch.object(runner, "get_cache_key", side_effect=RuntimeError("cache boundary")):
            with self.assertRaisesRegex(RuntimeError, "cache boundary"):
                runner.run(user=self.user)
        self.assertIs(runner.modifiers.useNewEventsSchema, True)

    def test_async_query_serializes_effective_table_without_changing_saved_source(self) -> None:
        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers)
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
            query=HogQLQuery(query="SELECT 1", modifiers=self.modifiers), team=self.team, user=self.user
        )
        effective = self.modifiers.model_copy(update={"useNewEventsSchema": True})
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
        modifiers = self.modifiers.model_copy(update={"useNewEventsSchema": native})
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
    def test_nested_async_choice_survives_enrollment_change_and_preserves_cache_identity(self, kind: str) -> None:
        query = self._nested_query(kind)
        original = query.model_dump()
        request = get_query_runner(query, self.team, user=self.user)
        cache = MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None)
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            request.enqueue_async_calculation(cache_manager=cache, user=self.user)
        with patch("posthog.models.event.new_events_schema.get_instance_setting", return_value=False):
            worker = get_query_runner(enqueue.call_args.kwargs["query_json"], self.team, user=self.user)
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
        query.modifiers = self.modifiers.model_copy(update={"useNewEventsSchema": not native})
        original = query.model_dump()
        with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com" if native else None):
            runner = get_query_runner(
                query,
                self.team,
                modifiers=self.modifiers.model_copy(update={"useNewEventsSchema": native}),
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
                query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsSchema": native})
            ),
            team=self.team,
        )
        with (
            patch.object(runner, "_get_property_access_restrictions", return_value=None),
            patch.object(runner, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            keys = []
            for host in (None, "native.example.com", "replacement.example.com"):
                with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=host):
                    keys.append(runner.get_cache_key())
        self.assertEqual(len(set(keys)), 3 if native else 1)

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
    def test_explicit_wrapper_schema_choice_takes_precedence_over_source_and_staff_default(self, native: bool) -> None:
        query = self._nested_query("ActorsQuery", not native)
        assert isinstance(query, ActorsQuery)
        query.modifiers = self.modifiers.model_copy(update={"useNewEventsSchema": native})
        runner = get_query_runner(query, self.team, user=self.user)
        assert isinstance(runner, ActorsQueryRunner)
        with patch.object(runner, "get_cache_key", side_effect=RuntimeError("cache boundary")):
            with self.assertRaisesRegex(RuntimeError, "cache boundary"):
                runner.run(user=self.user)
        self.assertIs(runner.modifiers.useNewEventsSchema, native)
        assert runner.source_query_runner is not None
        self.assertIs(runner.source_query_runner.modifiers.useNewEventsSchema, native)

    @parameterized.expand(
        [
            ("EventTaxonomyQuery", {"event": "example"}),
            ("PropertyValuesQuery", {"property_key": "example", "property_type": "event"}),
            ("SessionsTimelineQuery", {}),
            ("FunnelCorrelationQuery", {}),
        ]
    )
    def test_schema_sensitive_runner_follows_late_user_before_execution(
        self, kind: str, fields: dict[str, object]
    ) -> None:
        query = self._nested_query(kind) if kind == "FunnelCorrelationQuery" else {"kind": kind, **fields}
        runner = get_query_runner(query, self.team, modifiers=self.modifiers)
        self.assertIs(runner._use_new_events_schema, False)
        with patch.object(runner, "get_cache_key", side_effect=RuntimeError("cache boundary")):
            with self.assertRaisesRegex(RuntimeError, "cache boundary"):
                runner.run(user=self.user)
        self.assertIs(runner.modifiers.useNewEventsSchema, True)
        self.assertIs(runner._use_new_events_schema, True)
        if kind == "FunnelCorrelationQuery":
            assert isinstance(runner, FunnelCorrelationQueryRunner)
            self.assertIs(runner.context.modifiers.useNewEventsSchema, True)
            self.assertIs(runner.context.user, self.user)

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

    def test_resolved_legacy_choice_cannot_change_after_enrollment_changes(self) -> None:
        ordinary = User(id=124, is_staff=True, is_active=True)
        initial = create_default_modifiers_for_user(ordinary, self.team, self.modifiers)
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: '{"44": [124]}' if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
        ):
            self.assertIs(create_default_modifiers_for_user(ordinary, self.team, initial).useNewEventsSchema, False)

    def test_direct_hogql_execution_resolves_the_same_user_default(self) -> None:
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, user=self.user, modifiers=self.modifiers)
        self.assertIs(executor.query_modifiers.useNewEventsSchema, True)

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_table_executes_on_native_workload(self) -> None:
        executor = HogQLQueryExecutor(query="SELECT 1", team=self.team, user=self.user, modifiers=self.modifiers)
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
class TestNativeEventsUserQueryRouting(APIBaseTest):
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
        modifiers = HogQLQueryModifiers(useNewEventsSchema=native)
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
        enrollment = "{}" if native else json.dumps({str(self.team.id): [self.user.id]})
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: enrollment if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
            ),
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

    def test_user_opt_in_and_explicit_legacy_control_reach_the_correct_workloads(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        enrollment = json.dumps({str(self.team.id): [self.user.id]})
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: enrollment if key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_USERS" else False,
            ),
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
        ):
            native = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events"},
                    "refresh": "force_blocking",
                },
                format="json",
            )
            self.assertEqual(native.status_code, 200, native.json())
            self.assertIs(native.json()["modifiers"]["useNewEventsSchema"], True)
            self.assertEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)
            self.assertIn("events_json", execute.call_args.args[0])
            legacy = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "SELECT count() AS n FROM events",
                        "modifiers": {"useNewEventsSchema": False},
                    },
                    "refresh": "force_blocking",
                },
                format="json",
            )
            self.assertEqual(legacy.status_code, 200, legacy.json())
            self.assertIs(legacy.json()["modifiers"]["useNewEventsSchema"], False)
            self.assertNotEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)
            self.assertNotIn("events_json", execute.call_args.args[0])
            self.assertNotEqual(native.json()["cache_key"], legacy.json()["cache_key"])
