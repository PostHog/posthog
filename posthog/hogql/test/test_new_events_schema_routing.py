from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
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

    @parameterized.expand([(False,), (None,)])
    def test_raw_native_opt_in_cannot_be_enqueued_with_a_constructor_override(self, override: bool | None) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        runner = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True})
            ),
            team=self.team,
            modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": override}),
        )
        with self.assertRaisesRegex(ExposedHogQLError, "synchronous execution"):
            self._enqueue(runner)

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

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_cluster_opt_in_executes_on_native_workload(self) -> None:
        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            user=self.user,
            modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}),
        )
        self.assertIs(executor.query_modifiers.useNewEventsSchema, True)
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
            ({"useNewEventsCluster": True}, True, True, True),
            ({"useNewEventsCluster": True}, False, False, True),
            ({}, True, False, False),
            ({"useNewEventsSchema": True}, True, True, False),
            ({"useNewEventsCluster": False, "useNewEventsSchema": True}, True, True, False),
        ]
    )
    def test_query_route_requires_explicit_cluster_opt_in_and_project_eligibility(
        self, modifiers: dict[str, bool], eligible: bool, native_table: bool, native_cluster: bool
    ) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: (
                    [self.team.id] if eligible and key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False
                ),
            ),
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
        ):
            response = self._run_sql(modifiers)
        self.assertEqual(response.status_code, 400 if native_cluster and not eligible else 200, response.json())
        if response.status_code == 400:
            execute.assert_not_called()
            return
        self.assertEqual("events_json" in execute.call_args.args[0], native_table)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NATIVE_EVENTS, native_cluster)
        if native_cluster:
            self.assertIs(response.json()["modifiers"]["useNewEventsCluster"], True)

    @parameterized.expand([("force_async", False), ("force_blocking", True)])
    def test_native_async_dispatch_is_rejected_before_enqueue(self, refresh: str, async_: bool) -> None:
        with (
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect=lambda key: [self.team.id] if key == "CLICKHOUSE_NATIVE_EVENTS_TEAMS" else False,
            ),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            response = self._run_sql({"useNewEventsCluster": True}, refresh=refresh, async_=async_)
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("synchronous execution", str(response.json()))
        enqueue.assert_not_called()

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
