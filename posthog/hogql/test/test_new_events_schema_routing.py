from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.models import Organization, Team, User
from posthog.models.event.new_events_schema import NEW_EVENTS_SCHEMA_COOKIE, events_read_http_url
from posthog.models.instance_setting import override_instance_config

SQL_ON_EVENTS: dict[str, object] = {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events"}
SQL_ON_NO_TABLE: dict[str, object] = {"kind": "HogQLQuery", "query": "SELECT 1 AS n"}


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
            ("events_json", "native.example.com", True, "https://native.example.com:8443/"),
            ("legacy_table", "native.example.com", False, None),
            ("no_host", "", True, None),
        ]
    )
    def test_the_http_clients_get_the_events_cluster_url(
        self, _name: str, host: str, reads_events_json: bool, expected: str | None
    ) -> None:
        self.instance_settings.update(CLICKHOUSE_NATIVE_EVENTS_HOST=host)
        context = HogQLContext(team_id=self.team.pk, reads_native_events_table=reads_events_json)
        with self.settings(CLICKHOUSE_HTTP_URL="https://main.example.com:8443/"):
            self.assertEqual(events_read_http_url(context), expected)

    @parameterized.expand(
        [
            ("events_json", "native.example.com", True, Workload.DEFAULT, Workload.NEW_EVENTS_CLUSTER),
            ("offline_query", "native.example.com", True, Workload.OFFLINE, Workload.NEW_EVENTS_CLUSTER),
            ("legacy_table", "native.example.com", False, Workload.DEFAULT, Workload.DEFAULT),
            ("no_host", "", True, Workload.DEFAULT, Workload.DEFAULT),
            ("logs_cluster", "native.example.com", True, Workload.LOGS, Workload.LOGS),
        ]
    )
    def test_a_query_that_read_events_json_runs_on_the_events_cluster(
        self, _name: str, host: str, reads_events_json: bool, workload: Workload, expected: Workload
    ) -> None:
        self.instance_settings.update(CLICKHOUSE_NATIVE_EVENTS_HOST=host)
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

    def test_a_stored_project_modifier_does_not_switch_the_events_table(self) -> None:
        self.team.modifiers = {"useNewEventsSchema": True, "bounceRateDurationSeconds": 30}
        modifiers = create_default_modifiers_for_team(
            self.team, HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        )
        self.assertIsNone(modifiers.useNewEventsSchema)
        self.assertEqual(modifiers.bounceRateDurationSeconds, 30)


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsClusterRoutingThroughTheQueryApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"))
        self.enterContext(override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", False))

    def _post_query(self, query: dict[str, object], modifiers: dict[str, bool]) -> MagicMock:
        with patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute:
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {"query": {**query, "modifiers": modifiers}, "refresh": "force_blocking"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.json())
        return execute

    @parameterized.expand(
        [
            ("sql_on_events_json", SQL_ON_EVENTS, {"useNewEventsSchema": True}, True),
            ("sql_on_legacy_events", SQL_ON_EVENTS, {}, False),
            ("sql_reading_no_events", SQL_ON_NO_TABLE, {"useNewEventsSchema": True}, False),
        ]
    )
    def test_a_query_that_reads_events_json_runs_on_the_events_cluster(
        self, _name: str, query: dict[str, object], modifiers: dict[str, bool], events_json: bool
    ) -> None:
        execute = self._post_query(query, modifiers)
        self.assertEqual("events_json" in execute.call_args.args[0], events_json)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NEW_EVENTS_CLUSTER, events_json)

    @parameterized.expand(
        [
            ("staff", True, False, {}, True),
            ("staff_query_pinned_to_legacy", True, False, {"useNewEventsSchema": False}, False),
            ("staff_impersonating_a_customer", True, True, {}, True),
            ("not_staff", False, False, {}, False),
        ]
    )
    def test_the_cookie_switches_a_staff_persons_requests_to_events_json(
        self, _name: str, staff: bool, impersonating: bool, modifiers: dict[str, bool], events_json: bool
    ) -> None:
        self.user.is_staff = staff
        self.user.save()
        if impersonating:
            customer = User.objects.create_and_join(self.organization, "customer@example.com", None)
            self.client.post(
                reverse("loginas-user-login", kwargs={"user_id": customer.id}),
                data={"read_only": "false", "reason": "Checking the native table"},
                follow=True,
            )
            self.assertEqual(self.client.get("/api/users/@me").json()["email"], customer.email)
        self.client.cookies[NEW_EVENTS_SCHEMA_COOKIE] = "1"

        execute = self._post_query(SQL_ON_EVENTS, modifiers)
        self.assertEqual("events_json" in execute.call_args.args[0], events_json)
        self.assertEqual(execute.call_args.kwargs["workload"] == Workload.NEW_EVENTS_CLUSTER, events_json)
