from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models import Organization, Team, User
from posthog.models.instance_setting import override_instance_config


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
class TestNewEventsClusterRouting(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=44, modifiers={}, organization=Organization(id=1))
        self.user = User(id=123, is_staff=True, is_active=True)
        self.modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        self.instance_settings: dict[str, object] = {
            "CLICKHOUSE_NATIVE_EVENTS_TEAMS": [44],
            "CLICKHOUSE_NATIVE_EVENTS_HOST": "native.example.com",
        }
        self.enterContext(
            patch("posthog.models.event.new_events_schema.get_instance_setting", self.instance_settings.get)
        )
        self.enterContext(
            patch(
                "products.web_analytics.backend.hogql_queries.cookieless_flag.resolve_cookieless_traffic_is_regular_modifier",
                return_value=True,
            )
        )

    @parameterized.expand(
        [
            ([], "native.example.com", "not enabled"),
            ([44, True], "native.example.com", "not enabled"),
            ([44], None, "host is not configured"),
        ]
    )
    def test_unavailable_native_route_fails_closed(self, allowed: object, host: str | None, error: str) -> None:
        self.instance_settings.update(CLICKHOUSE_NATIVE_EVENTS_HOST=host, CLICKHOUSE_NATIVE_EVENTS_TEAMS=allowed)
        with self.assertRaisesRegex(ExposedHogQLError, error):
            HogQLQueryRunner(
                query=HogQLQuery(
                    query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True})
                ),
                team=self.team,
            )

    def test_direct_warehouse_connection_cannot_claim_native_cluster_opt_in(self) -> None:
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
                self.instance_settings["CLICKHOUSE_NATIVE_EVENTS_HOST"] = host
                keys.append(runner.get_cache_key())
        self.assertEqual(len(set(keys)), 2 if native else 1)

    @parameterized.expand(
        [
            (
                workload,
                None,
                workload in (Workload.DEFAULT, Workload.ONLINE, Workload.OFFLINE, Workload.NEW_EVENTS_CLUSTER),
            )
            for workload in Workload
        ]
        + [(Workload.DEFAULT, Product.ENDPOINTS, False)]
    )
    def test_native_opt_in_accepts_only_analytics_workloads(
        self, workload: Workload, product: Product | None, supported: bool
    ) -> None:
        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            workload=workload,
            modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}),
        )
        executor.select_query = ast.SelectQuery(select=[ast.Constant(value=1)])
        executor.clickhouse_sql = "SELECT 1"
        executor.clickhouse_context = HogQLContext(team_id=self.team.pk, modifiers=executor.query_modifiers)
        with (
            tags_context(product=product),
            patch.object(executor, "_detect_warehouse_sources"),
            patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
        ):
            if supported:
                executor._execute_clickhouse_query()
                self.assertEqual(execute.call_args.kwargs["workload"], Workload.NEW_EVENTS_CLUSTER)
            else:
                with self.assertRaisesRegex(ExposedHogQLError, "analytics workloads only"):
                    executor._execute_clickhouse_query()
                execute.assert_not_called()


@override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestNewEventsClusterPilot(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"))
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]))
        self.enterContext(override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", False))

    @parameterized.expand(
        [
            (modifiers, eligible, native_table, native_cluster)
            for modifiers, eligible, native_table, native_cluster in (
                ({"useNewEventsCluster": True}, True, True, True),
                ({"useNewEventsCluster": True}, False, False, True),
                ({}, True, False, False),
                ({"useNewEventsSchema": True}, True, True, False),
                ({"useNewEventsCluster": False, "useNewEventsSchema": True}, True, True, False),
            )
        ]
        + [
            (
                {"useNewEventsCluster": True, modifier: True},
                True,
                True,
                True,
                sql,
            )
            for modifier, sql in (
                ("usePreaggregatedTableTransforms", "SELECT count() FROM events WHERE event = '$pageview'"),
                (
                    "usePreaggregatedIntermediateResults",
                    "SELECT toStartOfDay(timestamp), uniqExact(person_id) FROM events WHERE event = '$pageview' AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' GROUP BY toStartOfDay(timestamp)",
                ),
            )
        ]
        + [
            ({"useNewEventsCluster": True}, True, True, True, "SELECT 1", "force_async"),
            ({"useNewEventsCluster": True}, True, True, True, "SELECT 1", "force_blocking", True),
            (
                {"useNewEventsCluster": True},
                True,
                True,
                True,
                {"kind": "PropertyValuesQuery", "property_key": "$browser", "property_type": "event"},
            ),
        ]
    )
    def test_query_route_requires_an_eligible_explicit_blocking_opt_in(
        self,
        modifiers: dict[str, bool],
        eligible: bool,
        native_table: bool,
        native_cluster: bool,
        sql: str | dict[str, str] = "SELECT count() AS n FROM events",
        refresh: str = "force_blocking",
        async_: bool = False,
    ) -> None:
        query = {"kind": "HogQLQuery", "query": sql} if isinstance(sql, str) else sql
        unsupported = native_cluster and (query["kind"] != "HogQLQuery" or refresh != "force_blocking" or async_)
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk] if eligible else []),
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute",
                return_value=0,
            ) as insert,
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {**query, "modifiers": modifiers},
                    "refresh": refresh,
                    "async": async_,
                },
                format="json",
            )
        rejected = native_cluster and (not eligible or unsupported)
        self.assertEqual(response.status_code, 400 if rejected else 200, response.json())
        enqueue.assert_not_called()
        if rejected:
            execute.assert_not_called()
            if unsupported:
                self.assertIn("Native cluster comparisons", response.json()["detail"])
            return
        self.assertEqual("events_json" in execute.call_args.args[0], native_table)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NEW_EVENTS_CLUSTER, native_cluster)
        if native_cluster:
            insert.assert_not_called()
            self.assertNotIn("pre_aggregated", execute.call_args.args[0])
            self.assertNotIn("preaggregation_results", execute.call_args.args[0])
            self.assertIs(response.json()["modifiers"]["useNewEventsCluster"], True)
