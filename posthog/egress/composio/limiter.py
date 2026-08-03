"""Outbound Composio API budgets.

Two meters, drawn from together on every call:

- ``composio`` — the real external meter. Composio rate limits per account, and we run one
  PostHog-owned account for all customers, so this is an instance-wide budget keyed on a
  fingerprint of the configured API key (never a PostHog row id — see the egress README).
- ``composio_team`` — a fairness guard, not an external meter. Without it one team's runaway
  agent loop spends the whole instance budget and every other team's tool calls start failing.
"""

from django.conf import settings

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

COMPOSIO_DOMAIN = "composio"
COMPOSIO_TEAM_DOMAIN = "composio_team"


def _composio_policy(_key: str) -> RatePolicy:
    return RatePolicy(
        limits=(
            (int(getattr(settings, "COMPOSIO_EGRESS_PER_MINUTE_BUDGET", 6_000)), 60.0),
            (int(getattr(settings, "COMPOSIO_EGRESS_HOURLY_BUDGET", 120_000)), 3600.0),
        ),
        in_memory_divider=4,
    )


def _composio_team_policy(_key: str) -> RatePolicy:
    return RatePolicy(
        limits=(
            (int(getattr(settings, "COMPOSIO_TEAM_EGRESS_PER_MINUTE_BUDGET", 300)), 60.0),
            (int(getattr(settings, "COMPOSIO_TEAM_EGRESS_HOURLY_BUDGET", 5_000)), 3600.0),
        ),
        in_memory_divider=4,
    )


register_policy(COMPOSIO_DOMAIN, _composio_policy)
register_policy(COMPOSIO_TEAM_DOMAIN, _composio_team_policy)


def consume_composio_account_sync(account_fingerprint: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{COMPOSIO_DOMAIN}:api_key:{account_fingerprint}",
        priority=priority,
        source=source,
    )


def consume_composio_team_sync(team_id: int, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{COMPOSIO_TEAM_DOMAIN}:team:{team_id}",
        priority=priority,
        source=source,
    )
