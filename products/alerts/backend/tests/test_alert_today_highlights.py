import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema_enums import AlertState

from products.alerts.backend import today_highlights
from products.alerts.backend.facade.contracts import FiringAlert
from products.alerts.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight
from products.today.backend.facade.testing import highlight_context


class TestAlerts(BaseTest):
    @parameterized.expand(
        [
            (
                "the kind word is cut from the alert name",
                "Checkout conversion alert",
                "Checkout funnel",
                "Alert ‘Checkout conversion’ is firing",
                "Insight ‘Checkout funnel’",
            ),
            ("an unnamed insight shows its id", "Signups", None, "Alert ‘Signups’ is firing", "Insight ‘abc123’"),
            ("an unnamed alert", "", "Checkout funnel", "An alert is firing", "Insight ‘Checkout funnel’"),
        ]
    )
    def test_each_firing_alert_is_one_risk_item(
        self, _name: str, alert_name: str, insight_name: str | None, title: str, detail: str
    ) -> None:
        alert = FiringAlert(id=uuid.uuid4(), name=alert_name, insight_name=insight_name, insight_short_id="abc123")
        registered = next(s for s in HIGHLIGHT_SOURCES if s.name == "alerts")

        with patch.object(today_highlights, "list_firing_alerts_created_by", return_value=[alert]):
            found = registered.find(highlight_context(team=self.team, user=self.user, today=date(2026, 10, 13)))

        self.assertEqual(
            [(c.key, c.title, c.detail, c.url) for c in found.items],
            [(f"alert:{alert.id}", title, detail, "/insights/abc123")],
        )

    @parameterized.expand(
        [
            ("a session", None, True),
            ("a key with the metrics scope", frozenset({"alert:read", "metrics:read"}), True),
            ("a key without it", frozenset({"alert:read"}), False),
        ]
    )
    def test_metrics_insight_alerts_follow_the_metrics_scope(
        self, _name: str, scopes: frozenset[str] | None, include: bool
    ) -> None:
        listed = MagicMock(return_value=[])
        registered = next(s for s in HIGHLIGHT_SOURCES if s.name == "alerts")

        with patch.object(today_highlights, "list_firing_alerts_created_by", listed):
            registered.find(highlight_context(team=self.team, user=self.user, today=date(2026, 10, 13), scopes=scopes))

        self.assertEqual(listed.call_args.kwargs["include_metrics_insights"], include)

    def test_only_alerts_that_started_firing_today_are_news(self) -> None:
        end = datetime.now(UTC)
        for name, checks in (
            ("Started today", [(AlertState.NOT_FIRING, 5), (AlertState.FIRING, 3)]),
            ("Firing all week", [(AlertState.FIRING, 72), (AlertState.FIRING, 3)]),
        ):
            alert = AlertConfiguration.objects.create(
                team=self.team,
                insight=Insight.objects.create(team=self.team, name=name),
                name=name,
                state=AlertState.FIRING,
            )
            AlertConfiguration.objects.filter(id=alert.id).update(created_at=end - timedelta(days=7))
            for state, hours_ago in checks:
                check = AlertCheck.objects.create(alert_configuration=alert, state=state)
                AlertCheck.objects.filter(id=check.id).update(created_at=end - timedelta(hours=hours_ago))
        context = SimpleNamespace(
            team=self.team,
            start=end - timedelta(days=1),
            end=end,
            shared=lambda _resource: True,
            withheld=lambda _resource: frozenset(),
        )

        facts = today_highlights.find_firing_alert_news(context)

        self.assertEqual(
            [(fact.kind, fact.title, fact.numbers.get("alerts")) for fact in facts],
            [
                ("alert_firing", "Started today", None),
                ("alerts_still_firing", "Alerts still firing from before today", 1),
            ],
        )
