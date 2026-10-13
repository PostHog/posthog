from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Organization, Team, User


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

    def _enqueue(self, runner: QueryRunner) -> dict[str, Any]:
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(
                cache_manager=MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None), user=self.user
            )
        return enqueue.call_args.kwargs["query_json"]

    @parameterized.expand(
        [
            ([], "native.example.com", "not enabled"),
            ([44, True], "native.example.com", "not enabled"),
            (["44"], "native.example.com", "not enabled"),
            ({"44": True}, "native.example.com", "not enabled"),
            ([44], None, "host is not configured"),
        ]
    )
    def test_unavailable_native_route_fails_closed(self, allowed: object, host: str | None, error: str) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        with (
            override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST=host),
            patch("posthog.models.event.new_events_schema.get_instance_setting", return_value=allowed),
        ):
            with self.assertRaisesRegex(ExposedHogQLError, error):
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

    def test_direct_warehouse_connection_cannot_claim_native_cluster_opt_in(self) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        with self.assertRaisesRegex(ExposedHogQLError, "warehouse connection"):
            HogQLQueryExecutor(
                query="SELECT 1",
                team=self.team,
                modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}),
                connection_id="example-connection",
            )

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

    def test_worker_revalidates_eligibility_instead_of_falling_back(self) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}))
        runner = HogQLQueryRunner(query=source, team=self.team)
        serialized = self._enqueue(runner)
        with patch("posthog.models.event.new_events_schema.get_instance_setting", return_value=[]):
            with self.assertRaisesRegex(ExposedHogQLError, "not enabled"):
                get_query_runner(serialized, self.team, user=self.user)

    @parameterized.expand(
        [
            ("native", {"useNewEventsCluster": True}, None, {}, True, True),
            ("legacy", {}, None, {}, False, None),
            ("schema_override", {}, {"useNewEventsSchema": False}, {"useNewEventsSchema": True}, False, None),
            ("cluster_false", {"useNewEventsCluster": True}, {"useNewEventsCluster": False}, {}, False, False),
            ("cluster_unset", {"useNewEventsCluster": True}, {"useNewEventsCluster": None}, {}, False, None),
        ]
    )
    def test_async_route_and_cache_identity_survive_worker_reconstruction(
        self, name: str, raw: dict, override: dict | None, team_defaults: dict, schema: bool, cluster: bool | None
    ) -> None:
        self.team.modifiers = team_defaults
        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers.model_copy(update=raw))
        original = source.model_dump()
        with override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com" if cluster else None):
            request = HogQLQueryRunner(
                query=source,
                team=self.team,
                user=self.user,
                modifiers=self.modifiers.model_copy(update=override) if override is not None else None,
            )
            serialized = self._enqueue(request)
            worker = get_query_runner(serialized, self.team, user=self.user)
        self.assertIs(worker.modifiers.useNewEventsSchema, schema)
        self.assertIs(worker.modifiers.useNewEventsCluster, cluster)
        self.assertEqual(source.model_dump(), original)
        if name == "legacy":
            self.assertEqual(serialized, original)
        with (
            patch.object(request, "_get_property_access_restrictions", return_value=None),
            patch.object(worker, "_get_property_access_restrictions", return_value=None),
            patch.object(request, "_products_modifiers_for_cache", return_value={}),
            patch.object(worker, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            if override is None:
                self.assertEqual(request.get_cache_payload(), worker.get_cache_payload())

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_direct_trino_queue_preserves_pure_inputs(self) -> None:
        from posthog.hogql.transforms.trino.manifest import TrinoCatalogManifest, transpile_hogql_to_trino

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.DISABLED}
        query = HogQLQuery(query="SELECT 1", connectionId="example-connection")
        user = self.user
        source = MagicMock(direct_engine="trino", has_managed_warehouse_prefix=False)
        with patch("posthog.hogql_queries.hogql_query_runner.get_direct_connection_source", return_value=source):
            runner = HogQLQueryRunner(query=query, team=self.team, user=user)
            serialized = self._enqueue(runner)
            worker = get_query_runner(serialized, self.team, user=user)
        assert isinstance(worker, HogQLQueryRunner)
        compiled = transpile_hogql_to_trino(
            worker.query.query,
            manifest=TrinoCatalogManifest(tables=()),
            filters=worker.query.filters,
            variables=worker.query.variables,
            modifiers=worker.query.modifiers,
        )
        self.assertIn("SELECT 1", compiled.sql)
        self.assertEqual(serialized, query.model_dump())


@override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestNewEventsClusterPilot(APIBaseTest):
    def _run_sql(self, modifiers: dict[str, bool], refresh: str = "force_blocking", async_: bool = False):
        return self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {
                "query": {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events", "modifiers": modifiers},
                "refresh": refresh,
                "async": async_,
            },
            format="json",
        )

    @parameterized.expand(
        [
            (modifiers, eligible, native_table, native_cluster, "force_blocking", False)
            for modifiers, eligible, native_table, native_cluster in (
                ({"useNewEventsCluster": True}, True, True, True),
                ({"useNewEventsCluster": True}, False, False, True),
                ({}, True, False, False),
                ({"useNewEventsSchema": True}, True, True, False),
                ({"useNewEventsCluster": False, "useNewEventsSchema": True}, True, True, False),
            )
        ]
    )
    def test_query_route_requires_an_eligible_explicit_opt_in(
        self,
        modifiers: dict[str, bool],
        eligible: bool,
        native_table: bool,
        native_cluster: bool,
        refresh: str,
        async_: bool,
    ) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: (
                    [self.team.id] if eligible and key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False
                ),
            ),
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            response = self._run_sql(modifiers, refresh=refresh, async_=async_)
        rejected = native_cluster and not eligible
        self.assertEqual(response.status_code, 400 if rejected else 200, response.json())
        enqueue.assert_not_called()
        if rejected:
            execute.assert_not_called()
            return
        self.assertEqual("events_json" in execute.call_args.args[0], native_table)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NATIVE_EVENTS, native_cluster)
        if native_cluster:
            self.assertIs(response.json()["modifiers"]["useNewEventsCluster"], True)

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

    @parameterized.expand([(False,), (True,)])
    def test_property_values_native_opt_in_bypasses_the_aggregate_table(self, native: bool) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: [self.team.id] if key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False,
            ),
            patch(
                "posthog.hogql_queries.property_values_query_runner.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "property-values-table",
            ),
            patch(
                "posthog.hogql_queries.utils.aggregated_property_values.sync_execute", return_value=[('"Chrome"',)]
            ) as aggregate,
            patch("posthog.hogql.query.sync_execute", return_value=([('"Chrome"',)], [("value", "String")])) as execute,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {
                        "kind": "PropertyValuesQuery",
                        "property_type": "event",
                        "property_key": "browser",
                        "modifiers": {"useNewEventsSchema": native, "useNewEventsCluster": native},
                    },
                    "refresh": "force_blocking",
                    "async": False,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(aggregate.called, not native)
        self.assertEqual(execute.called, native)
        if native:
            self.assertIn("events_json", execute.call_args.args[0])
            self.assertEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)

    @parameterized.expand(
        [
            (True, False, "SELECT count() FROM events WHERE event = '$pageview'"),
            (
                False,
                True,
                "SELECT toStartOfDay(timestamp), uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' GROUP BY toStartOfDay(timestamp)",
            ),
            (
                True,
                True,
                "SELECT toStartOfDay(timestamp), uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' GROUP BY toStartOfDay(timestamp)",
            ),
        ]
    )
    def test_native_sql_bypasses_aggregate_optimizers(self, tables: bool, intermediate: bool, sql: str) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: [self.team.pk] if key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False,
            ),
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute",
                return_value=0,
            ) as insert,
            patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/query/",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": sql,
                        "modifiers": {
                            "useNewEventsCluster": True,
                            "usePreaggregatedTableTransforms": tables,
                            "usePreaggregatedIntermediateResults": intermediate,
                        },
                    },
                    "refresh": "force_blocking",
                    "async": False,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.json())
        insert.assert_not_called()
        self.assertIn("events_json", execute.call_args.args[0])
        self.assertNotIn("pre_aggregated", execute.call_args.args[0])
        self.assertNotIn("preaggregation_results", execute.call_args.args[0])
        self.assertEqual(execute.call_args.kwargs["workload"], Workload.NATIVE_EVENTS)

    def test_nonstaff_cannot_enable_pilot_eligibility(self) -> None:
        response = self.client.patch(
            "/api/instance_settings/CLICKHOUSE_NATIVE_EVENTS_TEAMS", {"value": [self.team.id]}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.json())
