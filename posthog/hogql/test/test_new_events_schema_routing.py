from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.models import Organization, Team
from posthog.models.event.new_events_schema import events_read_http_url
from posthog.models.instance_setting import override_instance_config

SQL_ON_EVENTS = {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events"}
SQL_ON_NO_TABLE = {"kind": "HogQLQuery", "query": "SELECT 1 AS n"}


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsClusterRouting(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=44, modifiers={}, organization=Organization(id=1))
        self.instance_settings: dict[str, object] = {}
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
            ("listed_project", [44], True, "https://native.example.com:8443/"),
            ("legacy_table", [44], False, None),
            ("unlisted_project", [], True, None),
        ]
    )
    def test_the_http_clients_get_the_events_cluster_url(
        self, _name: str, allowed: list[object], reads_events_json: bool, expected: str | None
    ) -> None:
        self.instance_settings.update(
            CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com", CLICKHOUSE_NATIVE_EVENTS_TEAMS=allowed
        )
        context = HogQLContext(team_id=self.team.pk, reads_native_events_table=reads_events_json)
        with self.settings(CLICKHOUSE_HTTP_URL="https://main.example.com:8443/"):
            self.assertEqual(events_read_http_url(context), expected)

    @parameterized.expand(
        [
            ("listed_project", [44], "native.example.com", True, Workload.DEFAULT, Workload.NEW_EVENTS_CLUSTER),
            ("offline_query", [44], "native.example.com", True, Workload.OFFLINE, Workload.NEW_EVENTS_CLUSTER),
            ("legacy_table", [44], "native.example.com", False, Workload.DEFAULT, Workload.DEFAULT),
            ("unlisted_project", [], "native.example.com", True, Workload.DEFAULT, Workload.DEFAULT),
            ("malformed_list", [44, True], "native.example.com", True, Workload.DEFAULT, Workload.DEFAULT),
            ("no_host", [44], "", True, Workload.DEFAULT, Workload.DEFAULT),
            ("logs_cluster", [44], "native.example.com", True, Workload.LOGS, Workload.LOGS),
        ]
    )
    def test_a_query_that_read_events_json_runs_on_the_events_cluster(
        self,
        _name: str,
        allowed: list[object],
        host: str,
        reads_events_json: bool,
        workload: Workload,
        expected: Workload,
    ) -> None:
        self.instance_settings.update(CLICKHOUSE_NATIVE_EVENTS_HOST=host, CLICKHOUSE_NATIVE_EVENTS_TEAMS=allowed)
        executor = HogQLQueryExecutor(
            query="SELECT 1",
            team=self.team,
            workload=workload,
            modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED),
        )
        executor.select_query = ast.SelectQuery(select=[ast.Constant(value=1)])
        executor.clickhouse_sql = "SELECT 1"
        executor.clickhouse_context = HogQLContext(
            team_id=self.team.pk, modifiers=executor.query_modifiers, reads_native_events_table=reads_events_json
        )
        with (
            patch.object(executor, "_detect_warehouse_sources"),
            patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
        ):
            executor._execute_clickhouse_query()
        self.assertEqual(execute.call_args.kwargs["workload"], expected)


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsClusterRoutingThroughTheQueryApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"))
        self.enterContext(override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", False))

    @parameterized.expand(
        [
            ("sql_on_events_json", SQL_ON_EVENTS, {"useNewEventsSchema": True}, True, True, True),
            ("sql_on_legacy_events", SQL_ON_EVENTS, {}, True, False, False),
            ("sql_reading_no_events", SQL_ON_NO_TABLE, {"useNewEventsSchema": True}, True, False, False),
            ("unlisted_project", SQL_ON_EVENTS, {"useNewEventsSchema": True}, False, True, False),
        ]
    )
    def test_a_listed_projects_reads_of_events_json_run_on_the_events_cluster(
        self,
        _name: str,
        query: dict[str, object],
        modifiers: dict[str, bool],
        listed: bool,
        reads_events_json: bool,
        events_cluster: bool,
    ) -> None:
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk] if listed else []),
            patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {"query": {**query, "modifiers": modifiers}, "refresh": "force_blocking"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual("events_json" in execute.call_args.args[0], reads_events_json)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NEW_EVENTS_CLUSTER, events_cluster)
