from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.query_cache.read_history import read_since

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.product_analytics.backend.facade.models import Insight


def _hogql(sql: str) -> dict[str, Any]:
    return {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": sql}}


class TestDashboardFirstLoad(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(
            team=self.team, name="board", created_by=self.user, filters={"date_from": "-14d"}
        )

    def _add_tile(self, query: dict[str, Any]) -> Insight:
        insight = Insight.objects.create(team=self.team, query=query, created_by=self.user)
        DashboardTile.objects.create(dashboard=self.dashboard, insight=insight)
        return insight

    def _get(self, *, dashboard_v2: bool, refresh: str = "force_cache") -> dict[str, Any]:
        with patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            side_effect=lambda flag, *args, **kwargs: dashboard_v2 and flag in ("dashboard-v2", "dashboard-v2-users"),
        ):
            response = self.client.get(
                f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/", {"refresh": refresh}
            )
        assert response.status_code == 200, response.content
        return response.json()

    def test_tiles_are_identical_with_dashboard_v2(self) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="notebook_view",
            query={"kind": "HogQLQuery", "query": "select * from system.notebooks"},
        )
        self._add_tile(_hogql("select count() from events where event = '$pageview'"))
        self._add_tile(_hogql("select event, count() from events group by event"))
        self._add_tile(_hogql("select count() from notebook_view"))
        self._add_tile(_hogql("select * from notebook_view"))
        restricted = self._add_tile(_hogql("select count() from events where event = 'signed_up'"))

        self._get(dashboard_v2=False, refresh="blocking")

        # A member who can't see one insight, and whose notebook restriction must stay in the cache key of
        # every tile that reads the notebook view.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="insight", resource_id=str(restricted.id), access_level="none"
        )
        AccessControl.objects.create(team=self.team, resource="notebook", access_level="none")
        member = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)

        flag_off = self._get(dashboard_v2=False)["tiles"]
        flag_on = self._get(dashboard_v2=True)["tiles"]

        assert flag_on == flag_off
        insights = {tile["insight"]["id"]: tile["insight"] for tile in flag_on}
        assert insights[restricted.id] == {
            "id": restricted.id,
            "short_id": restricted.short_id,
            "user_access_level": "none",
        }
        assert sum(1 for insight in insights.values() if insight.get("is_cached")) == 2

    def test_postgres_queries_do_not_grow_with_tiles_on_dashboard_v2(self) -> None:
        def _queries_with(tiles: int) -> int:
            while self.dashboard.tiles.count() < tiles:
                self._add_tile(_hogql(f"select event from events where event != 'tile_{self.dashboard.tiles.count()}'"))
            with CaptureQueriesContext(connection) as ctx:
                self._get(dashboard_v2=True)
            return len(ctx.captured_queries)

        self._add_tile(_hogql("select count() from events where event = '$pageview'"))
        self._get(dashboard_v2=True)

        assert _queries_with(2) == _queries_with(5)

        now = timezone.now()
        read = read_since(team_id=self.team.pk, since=now - timedelta(hours=1), now=now)
        assert read == {f"{tile.insight_id}:{self.dashboard.id}" for tile in self.dashboard.tiles.all()}
