from datetime import UTC, datetime

import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team
from posthog.schema_enums import AlertState

from products.access_control.backend.models.access_control import AccessControl
from products.alerts.backend.facade import api, contracts
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


@time_machine.travel("2026-10-14T12:00:00Z", tick=False)
class TestListFiringAlertsCreatedBy(BaseTest):
    def _alert(
        self, team: Team, insight_fields: dict[str, object], alert_fields: dict[str, object]
    ) -> AlertConfiguration:
        insight = Insight.objects.create(
            **{"team": team, "name": "Checkout funnel", "created_by": self.user, **insight_fields}
        )
        return AlertConfiguration.objects.create(
            **{
                "team": team,
                "insight": insight,
                "name": "Checkout conversion",
                "state": AlertState.FIRING,
                "enabled": True,
                "created_by": self.user,
                **alert_fields,
            }
        )

    def _firing(self, include_metrics_insights: bool = True) -> list[contracts.FiringAlert]:
        return api.list_firing_alerts_created_by(
            self.team, self.user, include_metrics_insights=include_metrics_insights, limit=10
        )

    @parameterized.expand(
        [
            ("a named insight", {}, "Checkout funnel"),
            ("an unnamed insight", {"name": None, "derived_name": "Pageview count"}, "Pageview count"),
        ]
    )
    def test_lists_a_firing_alert_you_created(
        self, _name: str, insight_fields: dict[str, object], insight_name: str
    ) -> None:
        alert = self._alert(self.team, insight_fields, {})

        assert self._firing() == [
            contracts.FiringAlert(
                id=alert.id,
                name="Checkout conversion",
                insight_name=insight_name,
                insight_short_id=alert.insight.short_id,
            )
        ]

    @parameterized.expand(
        [
            ("its snooze has ended", {}, {"snoozed_until": datetime(2026, 10, 13, tzinfo=UTC)}, True),
            ("it is snoozed", {}, {"snoozed_until": datetime(2026, 10, 15, tzinfo=UTC)}, False),
            ("it is not firing", {}, {"state": AlertState.NOT_FIRING}, False),
            ("it is disabled", {}, {"enabled": False}, False),
            ("its insight is deleted", {"deleted": True}, {}, False),
        ]
    )
    def test_lists_an_alert_only_while_it_fires(
        self, _name: str, insight_fields: dict[str, object], alert_fields: dict[str, object], listed: bool
    ) -> None:
        self._alert(self.team, insight_fields, alert_fields)

        assert len(self._firing()) == (1 if listed else 0)

    def test_lists_only_your_alerts_in_this_project(self) -> None:
        teammate = self._create_user("other@example.com")
        yours = self._alert(self.team, {"created_by": teammate}, {})
        self._alert(self.team, {}, {"created_by": teammate})
        self._alert(Team.objects.create(organization=self.organization, name="Other project"), {}, {})

        assert [alert.id for alert in self._firing()] == [yours.id]

    def test_leaves_out_an_alert_whose_insight_you_cannot_view(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        viewable = self._alert(self.team, {}, {})
        hidden = self._alert(self.team, {"created_by": self._create_user("other@example.com")}, {})
        AccessControl.objects.create(
            resource="insight", resource_id=hidden.insight.id, team=self.team, access_level="none"
        )
        AlertConfiguration.objects.filter(id=hidden.id).update(created_at=datetime(2026, 10, 14, 13, tzinfo=UTC))

        assert [
            alert.id
            for alert in api.list_firing_alerts_created_by(self.team, self.user, include_metrics_insights=True, limit=1)
        ] == [viewable.id]

    @parameterized.expand(
        [
            ("a metrics insight with the metrics scope", {"kind": "MetricsQuery"}, True, True),
            ("a metrics insight without it", {"kind": "MetricsQuery"}, False, False),
            (
                "a wrapped metrics insight without it",
                {"kind": "InsightVizNode", "source": {"kind": "MetricsQuery"}},
                False,
                False,
            ),
            ("an insight with no query kind without it", {"source": {}}, False, True),
        ]
    )
    def test_metrics_insight_alerts_need_the_metrics_scope(
        self, _name: str, query: dict[str, object], include_metrics_insights: bool, listed: bool
    ) -> None:
        self._alert(self.team, {"query": query}, {})

        assert len(self._firing(include_metrics_insights)) == (1 if listed else 0)
