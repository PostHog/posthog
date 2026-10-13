from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
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
        with patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue:
            with self.assertRaisesRegex(ExposedHogQLError, "synchronous execution"):
                runner.enqueue_async_calculation(cache_manager=MagicMock(), user=self.user)
            enqueue.assert_not_called()

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
        + [
            ({"useNewEventsCluster": True}, True, True, True, refresh, async_)
            for refresh, async_ in (("force_async", False), ("force_blocking", True))
        ]
    )
    def test_query_route_requires_an_eligible_explicit_blocking_opt_in(
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
        rejected = native_cluster and (not eligible or refresh == "force_async" or async_)
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
