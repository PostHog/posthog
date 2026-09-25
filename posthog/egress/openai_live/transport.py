from typing import Any

import requests
from prometheus_client import Counter

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy
from posthog.egress.observability.observability import EgressMetrics, EgressObservability, scope_fingerprint
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

register_policy(
    "openai_live",
    per_minute_and_hourly_policy(
        per_minute_setting="OPENAI_LIVE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=6,
        hourly_setting="OPENAI_LIVE_EGRESS_HOURLY_BUDGET",
        hourly_default=30,
    ),
)


class OpenAILiveClient(EgressClient):
    observability = EgressObservability(
        EgressMetrics(
            request_counter=Counter(
                "openai_live_api_requests",
                "Outbound OpenAI Live session requests.",
                labelnames=["scope", "method", "endpoint", "status_code", "source"],
            )
        )
    )

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return get_outbound_rate_limiter().consume_sync(
            f"openai_live:account:{scope}", 1, priority=priority, source=source
        )

    def _budget_exhausted_error(self, scope: str) -> EgressBudgetExhausted:
        return EgressBudgetExhausted("OpenAI Live session budget exhausted")


def create_live_session(api_key: str, payload: dict[str, Any]) -> requests.Response:
    return OpenAILiveClient().request(
        "POST",
        "https://api.openai.com/v1/live/sessions",
        source="desktop_voice",
        scope=scope_fingerprint(api_key),
        priority=Priority.NORMAL,
        endpoint="live/sessions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=(5, 20),
    )
