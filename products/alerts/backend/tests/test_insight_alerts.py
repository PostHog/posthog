from types import SimpleNamespace
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.personal_api_key import PersonalAPIKey

from products.alerts.backend.presentation.views.insight_alerts import insight_alerts_hidden
from products.product_analytics.backend.facade.models import Insight

TRENDS = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}}
METRICS = {"kind": "InsightVizNode", "source": {"kind": "MetricsQuery"}}


def _token_request(scopes: list[str]) -> SimpleNamespace:
    authenticator = PersonalAPIKeyAuthentication()
    authenticator.personal_api_key = PersonalAPIKey(scopes=scopes)
    return SimpleNamespace(successful_authenticator=authenticator)


class TestInsightAlertsHidden(SimpleTestCase):
    @parameterized.expand(
        [
            ("shared_link", TRENDS, {"is_shared": True}, True),
            ("shared_page", TRENDS, {"hide_extra_details": True}, True),
            ("session", METRICS, {"request": SimpleNamespace(successful_authenticator=None)}, False),
            ("metrics_token_without_metrics_scope", METRICS, {"request": _token_request(["insight:read"])}, True),
            ("metrics_token_with_metrics_scope", METRICS, {"request": _token_request(["metrics:read"])}, False),
            ("trends_token_without_metrics_scope", TRENDS, {"request": _token_request(["insight:read"])}, False),
        ]
    )
    def test_hides_alerts(self, _name: str, query: dict, context: dict[str, Any], hidden: bool) -> None:
        assert insight_alerts_hidden(Insight(query=query), context) is hidden
