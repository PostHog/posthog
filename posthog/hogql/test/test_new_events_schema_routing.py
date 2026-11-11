import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Organization, Team, User
from posthog.models.event.new_events_schema import (
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

    def test_a_stored_project_modifier_does_not_switch_the_events_table(self) -> None:
        self.team.modifiers = {"useNewEventsSchema": True, "bounceRateDurationSeconds": 30}
        modifiers = create_default_modifiers_for_team(
            self.team, HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        )
        self.assertIsNone(modifiers.useNewEventsSchema)
        self.assertEqual(modifiers.bounceRateDurationSeconds, 30)

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
            # The login-as admin view reads a form post, and this client sends JSON unless told otherwise.
            self.client.post(
                reverse("loginas-user-login", kwargs={"user_id": customer.id}),
                data={"read_only": "false", "reason": "Checking the native table"},
                format="multipart",
                follow=True,
            )
            self.assertEqual(self.client.get("/api/users/@me").json()["email"], customer.email)
        self.client.cookies[NEW_EVENTS_SCHEMA_COOKIE] = "1"

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
