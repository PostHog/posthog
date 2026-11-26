from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.access_control import AccessControl
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_hooks import insight_alert_destination_edit_refusal
from products.product_analytics.backend.facade.models import Insight


class TestInsightAlertDestinationEditRefusal(BaseTest):
    @parameterized.expand(
        [
            ("member who can view the insight", {}, False, None, False),
            ("member who cannot view the insight", {}, True, None, True),
            (
                "token without a metrics scope on a metrics insight",
                {"kind": "MetricsQuery"},
                False,
                ["alert:write"],
                True,
            ),
            ("token with metrics read on a metrics insight", {"kind": "MetricsQuery"}, False, ["metrics:read"], False),
            (
                "token without a metrics scope on a SQL insight",
                {"kind": "HogQLQuery", "query": "select 1"},
                False,
                ["alert:write"],
                False,
            ),
        ]
    )
    def test_applies_the_insight_alert_apis_gates(
        self,
        _name: str,
        query: dict[str, object],
        insight_hidden: bool,
        key_scopes: list[str] | None,
        refused: bool,
    ) -> None:
        insight = Insight.objects.create(
            team=self.team,
            name="Queue depth",
            query=query,
            created_by=User.objects.create_and_join(self.organization, "other@example.com", None),
        )
        alert = AlertConfiguration.objects.create(team=self.team, insight=insight, name="Queue depth alert")
        if insight_hidden:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            AccessControl.objects.create(
                resource="insight", resource_id=insight.id, team=self.team, access_level="none"
            )

        refusal = insight_alert_destination_edit_refusal(
            team_id=self.team.id, alert_ids=[str(alert.id)], user_id=self.user.id, key_scopes=key_scopes
        )

        assert (refusal is not None) == refused, refusal
