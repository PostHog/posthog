from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT
from posthog.models.user import User
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.facade.destinations import list_alert_destination_groups, list_delivery_destination_groups
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription, Threshold
from products.alerts_platform.backend.facade.contracts import DestinationType
from products.product_analytics.backend.facade.models import Insight


class TestInsightAlertEmailDestination(APIBaseTest):
    def _alert(self, **overrides: Any) -> AlertConfiguration:
        insight = Insight.objects.create(
            team=self.team,
            name="insight",
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                interval=IntervalType.DAY,
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            ).model_dump(),
        )
        threshold = Threshold.objects.create(
            team=self.team, insight=insight, configuration={"type": "absolute", "bounds": {"upper": 100.0}}
        )
        fields: dict[str, Any] = {
            "team": self.team,
            "insight": insight,
            "name": "alert",
            "calculation_interval": AlertCalculationInterval.DAILY.value,
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "condition": {"type": "absolute_value"},
            "threshold": threshold,
        }
        fields.update(overrides)
        return AlertConfiguration.objects.create(**fields)

    def _subscribe(self, alert: AlertConfiguration, user: User) -> None:
        AlertSubscription.objects.create(user=user, alert_configuration=alert)

    @parameterized.expand([("firing", LEGACY_INSIGHT_ALERT_EVENT), ("errored", INSIGHT_ALERT_ERRORED_EVENT_ID)])
    def test_the_platform_emails_subscribers_who_can_still_see_the_alert(self, _name: str, event_id: str) -> None:
        alert = self._alert()
        self._subscribe(alert, self.user)
        self._subscribe(alert, User.objects.create(email="former-member@example.com"))

        groups = list_delivery_destination_groups(
            team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=[event_id]
        )

        assert [group.data for group in groups] == [
            {"type": DestinationType.EMAIL, "email_addresses": [self.user.email]}
        ]
        # The alert APIs list and delete through this one, so an email group there would read as a
        # destination a person could remove.
        assert (
            list_alert_destination_groups(team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=[event_id])
            == []
        )

    @parameterized.expand(
        [
            ("another_sources_event", True, None, "$logs_alert_firing"),
            ("an_alert_id_that_is_not_an_insight_alert", True, "legacy-logs-alert", LEGACY_INSIGHT_ALERT_EVENT),
            ("an_alert_nobody_subscribed_to", False, None, LEGACY_INSIGHT_ALERT_EVENT),
        ]
    )
    def test_no_email_group_without_an_insight_alert_and_a_subscriber(
        self, _name: str, subscribed: bool, alert_id: str | None, event_id: str
    ) -> None:
        alert = self._alert()
        if subscribed:
            self._subscribe(alert, self.user)

        groups = list_delivery_destination_groups(
            team_id=self.team.id, alert_id=alert_id or str(alert.id), allowed_event_ids=[event_id]
        )

        assert groups == []
