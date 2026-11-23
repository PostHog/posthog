import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload, events_cluster_host
from posthog.models import Organization, Team, User
from posthog.models.event.new_events_schema import (
    EVENTS_TABLE_ROLLOUT_FLAG,
    EVENTS_TABLE_SELF_SERVE_FLAG,
    NEW_EVENTS_SCHEMA_COOKIE,
    events_route_scope,
    new_events_schema_for_request,
    use_new_events_schema,
)
from posthog.models.instance_setting import override_instance_config

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight

SQL_ON_EVENTS: dict[str, object] = {"kind": "HogQLQuery", "query": "SELECT count() AS n FROM events"}


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsTableSwitch(SimpleTestCase):
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

    @contextmanager
    def _flag_on(self, flag_on: str | None) -> Iterator[MagicMock]:
        with (
            patch("posthog.models.event.new_events_schema.is_cloud", return_value=True),
            patch(
                "posthog.models.event.new_events_schema.posthoganalytics.feature_enabled",
                side_effect=lambda flag, *args, **kwargs: flag == flag_on,
            ) as feature_enabled,
        ):
            yield feature_enabled
        for flag_call in feature_enabled.call_args_list:
            self.assertEqual(flag_call.kwargs["groups"], {"project": str(self.team.pk)})
            self.assertEqual(flag_call.kwargs["group_properties"], {"project": {"id": str(self.team.pk)}})

    @parameterized.expand(
        [
            ("opted_in", True, True, None, None, True),
            ("opted_in_while_self_serve_is_closed", True, False, None, None, None),
            ("a_stored_false_cannot_choose_legacy", False, True, None, None, None),
            ("staff_tab_on_legacy", True, True, False, None, None),
            ("query_pinned_to_legacy", True, True, None, False, False),
        ]
    )
    def test_a_project_opt_in_moves_its_hogql_queries_unless_an_override_chose_a_table(
        self,
        _name: str,
        stored: bool,
        self_serve_open: bool,
        staff_switch: bool | None,
        query_modifier: bool | None,
        expected: bool | None,
    ) -> None:
        self.team.modifiers = {"useNewEventsSchema": stored, "bounceRateDurationSeconds": 30}
        staff_browser = nullcontext() if staff_switch is None else new_events_schema_for_request(staff_switch)
        with self._flag_on(EVENTS_TABLE_SELF_SERVE_FLAG if self_serve_open else None), staff_browser:
            modifiers = create_default_modifiers_for_team(
                self.team,
                HogQLQueryModifiers(
                    personsOnEventsMode=PersonsOnEventsMode.DISABLED, useNewEventsSchema=query_modifier
                ),
            )
            self.assertEqual(modifiers.useNewEventsSchema, expected)
            self.assertEqual(modifiers.bounceRateDurationSeconds, 30)
        # Readers that write their own SQL ask without modifiers, and an opt-in does not move them.
        self.assertFalse(use_new_events_schema(self.team.pk))

    def test_the_rollout_flag_moves_a_project_for_every_reader(self) -> None:
        with self._flag_on(EVENTS_TABLE_ROLLOUT_FLAG) as feature_enabled:
            self.assertTrue(use_new_events_schema(self.team.pk))
        feature_enabled.assert_called_once()

    def test_a_person_pinned_to_legacy_reads_legacy_on_an_allowlisted_project(self) -> None:
        self.instance_settings["CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS"] = str(self.team.pk)
        with new_events_schema_for_request(False):
            self.assertFalse(use_new_events_schema(self.team.pk))

    @parameterized.expand([(False, None, False), (True, None, True), (False, True, True), (True, False, False)])
    def test_nested_reads_inherit_the_querys_events_table(
        self, parent_schema: bool, child_schema: bool | None, expected: bool
    ) -> None:
        with new_events_schema_for_request(), events_route_scope(HogQLQueryModifiers(useNewEventsSchema=parent_schema)):
            self.assertEqual(
                use_new_events_schema(self.team.pk, HogQLQueryModifiers(useNewEventsSchema=child_schema)), expected
            )


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsTableSwitchThroughTheApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
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
            ("staff", True, False, "1", None, {}, True),
            ("staff_query_pinned_to_legacy", True, False, "1", None, {"useNewEventsSchema": False}, False),
            ("staff_impersonating_a_customer", True, True, "1", None, {}, True),
            ("not_staff", False, False, "1", None, {}, False),
            ("staff_tab_on_without_the_cookie", True, False, None, "1", {}, True),
            ("staff_tab_off_beside_the_cookie", True, False, "1", "0", {}, False),
            ("not_staff_tab_on", False, False, None, "1", {}, False),
        ]
    )
    def test_a_staff_persons_switch_routes_their_requests(
        self,
        _name: str,
        staff: bool,
        impersonating: bool,
        cookie: str | None,
        tab_header: str | None,
        modifiers: dict[str, bool],
        events_json: bool,
    ) -> None:
        self.user.is_staff = staff
        self.user.save()
        if impersonating:
            customer = User.objects.create_and_join(self.organization, "customer@example.com", None)
            # The login-as admin view reads a form post, and this client sends JSON unless told otherwise.
            self.client.post(
                reverse("loginas-user-login", kwargs={"user_id": customer.id}),
                data={"read_only": "false", "reason": "Checking the native table"},
                format="multipart",
                follow=True,
            )
            self.assertEqual(self.client.get("/api/users/@me").json()["email"], customer.email)
        if cookie is not None:
            self.client.cookies[NEW_EVENTS_SCHEMA_COOKIE] = cookie
        if tab_header is not None:
            self.client.credentials(HTTP_X_POSTHOG_NEW_EVENTS_SCHEMA=tab_header)

        execute = self._post_query(SQL_ON_EVENTS, modifiers)
        self.assertEqual("events_json" in execute.call_args.args[0], events_json)

    @parameterized.expand([("legacy", False), ("events_json", True)])
    def test_only_a_legacy_read_uses_the_preaggregated_web_tables(self, _name: str, events_json: bool) -> None:
        with patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute:
            execute_hogql_query(
                parse_select("select count(), uniq(person_id) from events where equals(event, '$pageview')"),
                team=self.team,
                modifiers=HogQLQueryModifiers(usePreaggregatedTableTransforms=True, useNewEventsSchema=events_json),
            )
        self.assertEqual("web_pre_aggregated_stats" in execute.call_args.args[0], not events_json)

    @parameterized.expand([("legacy", False, None), ("events_json", True, "events.example.com")])
    @override_settings(CLICKHOUSE_EVENTS_ONLINE_HOST="events.example.com")
    def test_the_connection_host_follows_the_printed_events_table(
        self, _name: str, events_json: bool, expected_host: str | None
    ) -> None:
        hosts: list[str | None] = []

        def record_host(*_args: object, **kwargs: object) -> tuple[list, list]:
            hosts.append(events_cluster_host(Workload.ONLINE, self.team.pk))
            return [], []

        with (
            override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", str(self.team.pk)),
            patch("posthog.hogql.query.sync_execute", side_effect=record_host),
        ):
            execute_hogql_query(
                parse_select("select count() from events"),
                team=self.team,
                modifiers=HogQLQueryModifiers(useNewEventsSchema=events_json),
            )
        self.assertEqual(hosts, [expected_host])

    def test_the_cookie_reaches_a_streamed_dashboards_cache_lookup(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.client.cookies[NEW_EVENTS_SCHEMA_COOKIE] = "1"
        insight = Insight.objects.create(
            team=self.team, filters={}, query={"kind": "DataVisualizationNode", "source": SQL_ON_EVENTS}
        )
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        with patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("n", "UInt64")])) as execute:
            response = self.client.get(
                f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/?refresh=force_blocking"
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertIn("events_json", execute.call_args.args[0])

        # The stream only reads the cache, so a hit here means the switch reached the lookup's cache key.
        self.assertIsNotNone(self._streamed_tile_result(dashboard.id))
        self.client.cookies[NEW_EVENTS_SCHEMA_COOKIE] = "0"
        self.assertIsNone(self._streamed_tile_result(dashboard.id))

    def _streamed_tile_result(self, dashboard_id: int) -> object:
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/stream_tiles/")
        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content).decode()  # type: ignore[attr-defined]
        metadata = next(
            line[6:] for line in content.split("\n") if line.startswith("data: ") and '"type":"metadata"' in line
        )
        return json.loads(metadata)["dashboard"]["tiles"][0]["insight"]["result"]
