"""Google Workspace egress budget, keyed by the connected Google account.

Gmail and Calendar meter quota per user per project, so the scope is the account's OAuth ``sub``.
Gmail allows 6,000 quota units per user per minute and ``users.messages.get`` costs 20, so the
per-minute default of 250 stays under Google's limit even when every call is a message fetch.

The policy is flat (``reserve={}``). Every scoped caller is a background sync that runs ``BATCH``,
so no higher lane needs headroom, and the default ladder would deny the sync at 70% of a budget
that already sits close to Google's own limit.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

GOOGLE_WORKSPACE_DOMAIN = "google_workspace"

register_policy(
    GOOGLE_WORKSPACE_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="GOOGLE_WORKSPACE_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=250,
        hourly_setting="GOOGLE_WORKSPACE_EGRESS_HOURLY_BUDGET",
        hourly_default=10_000,
        reserve={},
    ),
)


def consume_google_workspace_sync(account_id: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(
        f"{GOOGLE_WORKSPACE_DOMAIN}:account:{account_id}",
        priority=priority,
        source=source,
    )
