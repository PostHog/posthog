from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PersonsOnEventsMode, QueryStatus, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
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

    def _enqueue(self, runner: QueryRunner) -> dict[str, Any]:
        with (
            patch("posthog.hogql_queries.query_runner.posthoganalytics.capture"),
            patch("posthog.hogql_queries.query_runner.groups", return_value={}),
            patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue,
        ):
            runner.enqueue_async_calculation(
                cache_manager=MagicMock(cache_key="example-cache", insight_id=None, dashboard_id=None), user=self.user
            )
        self.runner_state = enqueue.call_args.kwargs.get("runner_state")
        return enqueue.call_args.kwargs["query_json"]

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

    def test_worker_revalidates_eligibility_instead_of_falling_back(self) -> None:
        from posthog.hogql.errors import ExposedHogQLError

        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsCluster": True}))
        runner = HogQLQueryRunner(query=source, team=self.team)
        serialized = self._enqueue(runner)
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: "native.example.com" if key == "CLICKHOUSE_NATIVE_EVENTS_HOST" else [],
        ):
            with self.assertRaisesRegex(ExposedHogQLError, "not enabled"):
                get_query_runner(serialized, self.team, user=self.user)

    @parameterized.expand(
        [
            ("native", {"useNewEventsCluster": True}, None, {}, True, True),
            ("legacy", {}, None, {}, False, None),
            ("schema_override", {}, {"useNewEventsSchema": False}, {"useNewEventsSchema": True}, False, None),
            ("cluster_false", {"useNewEventsCluster": True}, {"useNewEventsCluster": False}, {}, False, False),
            ("cluster_unset", {"useNewEventsCluster": True}, {"useNewEventsCluster": None}, {}, False, None),
            (
                "session_override",
                {"useNewEventsCluster": True, "sessionTableVersion": SessionTableVersion.V2},
                {"useNewEventsCluster": False, "sessionTableVersion": SessionTableVersion.V1},
                {},
                False,
                False,
            ),
        ]
    )
    def test_async_route_and_cache_identity_survive_worker_reconstruction(
        self, name: str, raw: dict, override: dict | None, team_defaults: dict, schema: bool, cluster: bool | None
    ) -> None:
        self.team.modifiers = team_defaults
        source = HogQLQuery(query="SELECT 1", modifiers=self.modifiers.model_copy(update=raw))
        original = source.model_dump()
        with patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: {
                "CLICKHOUSE_NATIVE_EVENTS_HOST": "native.example.com" if cluster else "",
                "CLICKHOUSE_NATIVE_EVENTS_TEAMS": [44],
            }.get(key, False),
        ):
            request = HogQLQueryRunner(
                query=source,
                team=self.team,
                user=self.user,
                modifiers=self.modifiers.model_copy(update=override) if override is not None else None,
            )
            serialized = self._enqueue(request)
            runner_state = self.runner_state
            worker = get_query_runner(
                runner_state["query"] if runner_state else serialized,
                self.team,
                user=self.user,
                modifiers=HogQLQueryModifiers.model_validate(runner_state["modifiers"]) if runner_state else None,
            )
            old_worker = get_query_runner(serialized, self.team, user=self.user)
            self.assertEqual(old_worker.modifiers, worker.modifiers)
        self.assertEqual(worker.modifiers.sessionTableVersion, request.modifiers.sessionTableVersion)
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
            patch.object(old_worker, "_get_property_access_restrictions", return_value=None),
            patch.object(old_worker, "_products_modifiers_for_cache", return_value={}),
            patch("posthog.hogql_queries.query_runner.events_retention_months_for_team", return_value=None),
        ):
            self.assertEqual(request.get_cache_payload(), worker.get_cache_payload())
            if override is not None:
                self.assertNotEqual(request.get_cache_key(), old_worker.get_cache_key())

    @parameterized.expand([(None,), (False,)])
    def test_legacy_enqueue_survives_native_host_lookup_failure(self, schema: bool | None) -> None:
        runner = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT 1", modifiers=self.modifiers.model_copy(update={"useNewEventsSchema": schema})
            ),
            team=self.team,
        )
        with patch(
            "posthog.hogql_queries.query_runner.get_new_events_cluster_host",
            side_effect=RuntimeError("settings unavailable"),
        ):
            queued = self._enqueue(runner)
        self.assertEqual(queued["query"], "SELECT 1")
        self.assertIsNot(queued["modifiers"].get("useNewEventsCluster"), True)

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

    def _run_query(self, query: dict, refresh: str = "force_blocking", async_: bool = False):
        return self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {"query": query, "refresh": refresh, "async": async_},
            format="json",
        )

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
            ({"useNewEventsCluster": True}, True, True, True, "SELECT count() AS n FROM events", "blocking"),
            ({"useNewEventsCluster": True}, True, True, True, "SELECT 1", "force_blocking", True),
            (
                {"useNewEventsCluster": True},
                True,
                True,
                True,
                {"kind": "GroupsQuery", "select": ["group_key"], "group_type_index": 0},
            ),
        ]
    )
    def test_query_route_requires_an_eligible_explicit_opt_in(
        self,
        modifiers: dict[str, bool],
        eligible: bool,
        native_table: bool,
        native_cluster: bool,
        sql: str | dict[str, Any] = "SELECT count() AS n FROM events",
        refresh: str = "force_blocking",
        async_: bool = False,
    ) -> None:
        query = {"kind": "HogQLQuery", "query": sql} if isinstance(sql, str) else sql
        unsupported = native_cluster and query["kind"] != "HogQLQuery"
        asynchronous = refresh == "force_async" or async_
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk] if eligible else []),
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.sync_execute",
                return_value=0,
            ) as insert,
            patch("posthog.hogql.query.sync_execute", return_value=([(7,)], [("n", "UInt64")])) as execute,
            patch(
                "posthog.hogql_queries.query_runner.enqueue_process_query_task",
                return_value=QueryStatus(id="native-test", team_id=self.team.pk, complete=False),
            ) as enqueue,
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
        self.assertEqual(response.status_code, 400 if rejected else 202 if asynchronous else 200, response.json())
        if asynchronous and not rejected:
            enqueue.assert_called_once()
            execute.assert_not_called()
            return
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

    @parameterized.expand([(False,), (True,)])
    def test_property_values_native_opt_in_bypasses_the_aggregate_table(self, native: bool) -> None:
        with (
            patch(
                "posthog.hogql_queries.property_values_query_runner.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "property-values-table",
            ),
            patch(
                "posthog.hogql_queries.utils.aggregated_property_values.sync_execute", return_value=[('"Chrome"',)]
            ) as aggregate,
            patch("posthog.hogql.query.sync_execute", return_value=([('"Chrome"',)], [("value", "String")])) as execute,
        ):
            response = self._run_query(
                {
                    "kind": "PropertyValuesQuery",
                    "property_type": "event",
                    "property_key": "browser",
                    "modifiers": {"useNewEventsSchema": native, "useNewEventsCluster": native},
                },
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(aggregate.called, not native)
        self.assertEqual(execute.called, native)
        if native:
            self.assertIn("events_json", execute.call_args.args[0])
            self.assertEqual(execute.call_args.kwargs["workload"], Workload.NEW_EVENTS_CLUSTER)
