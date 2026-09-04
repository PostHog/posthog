from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

import dateutil.parser

from ee.billing.quota_limiting import QuotaResource, get_fresh_team_limited_resources

if TYPE_CHECKING:
    from posthog.models import Team


def format_ai_credit_usage(team: Team) -> str:
    summary = (team.organization.usage or {}).get(QuotaResource.AI_CREDITS.value) or {}
    stored_usage = summary.get("usage")
    todays_usage = summary.get("todays_usage")
    used = None if stored_usage is None and todays_usage is None else (stored_usage or 0) + (todays_usage or 0)
    limit = summary.get("limit")
    limited = (
        team.organization.is_active is False
        or get_fresh_team_limited_resources(team.api_token)[QuotaResource.AI_CREDITS]
    )

    lines = ["*PostHog AI usage*", ""]
    if used is not None and isinstance(limit, int | float):
        used_credits = round(used)
        limit_credits = round(limit)
        lines.append(f"*Billing period*: {used_credits:,} of {limit_credits:,} credits")
        lines.append(f"*Remaining*: {max(0, limit_credits - used_credits):,} credits")
    elif used is not None:
        lines.append(f"*Billing period*: {round(used):,} credits used")
    else:
        lines.append("Billing period usage is not available yet.")

    lines.append(f"*Status*: {'Credit limit reached' if limited else 'Credits available'}")
    period = (team.organization.usage or {}).get("period")
    if isinstance(period, list) and len(period) >= 2 and isinstance(period[1], str):
        try:
            period_end = dateutil.parser.isoparse(period[1]).astimezone(UTC)
        except (TypeError, ValueError):
            pass
        else:
            lines.append(f"*Resets*: {period_end.strftime('%Y-%m-%d')}")

    lines.extend(["", "_Usage data may take a few minutes to update._"])
    return "\n".join(lines)
