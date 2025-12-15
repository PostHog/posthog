from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID

import posthoganalytics

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.tasks.usage_report import AI_BILLING_EXCLUDED_TOOLS, AI_COST_MARKUP_PERCENT, CLOUD_REGION_TO_TEAM_ID
from posthog.utils import get_instance_region

from ee.models.assistant import Conversation

# Default free tier limit in credits
DEFAULT_FREE_TIER_CREDITS = 2000

POSTHOG_AI_USAGE_REPORT_ASSISTANT_MESSAGE_TITLE = "PostHog AI usage"

# Default GA launch date - don't count usage before this date
DEFAULT_GA_LAUNCH_DATE = datetime(2025, 11, 17, tzinfo=UTC)

CH_BILLING_SETTINGS = {
    "max_execution_time": 60,  # 1 minute
}


def _get_billing_config_payload() -> dict | None:
    """
    Get the billing configuration payload from feature flag.
    Returns None if not available or invalid.

    Feature flag: posthog-ai-billing-free-tier-credits
    Expected payload format:
    {
        "ga_launch_date": "2025-11-17",  # ISO format date string (YYYY-MM-DD)
        "EU": {
            "1": 10000,  # team_id (as string): credits (as int)
            "2": 5000
        },
        "US": {
            "2": 10000
        }
    }
    """
    payload: dict | None = posthoganalytics.get_feature_flag_payload(  # type: ignore[assignment]
        "posthog-ai-billing-free-tier-credits", "internal_billing_events"
    )

    if isinstance(payload, dict):
        return payload
    return None


def get_ai_free_tier_credits(team_id: int) -> int:
    """
    Get the AI free tier credits limit for a team.
    Falls back to DEFAULT_FREE_TIER_CREDITS if not configured.
    """
    region = get_instance_region()
    if not region:
        return DEFAULT_FREE_TIER_CREDITS

    payload = _get_billing_config_payload()
    if not payload:
        return DEFAULT_FREE_TIER_CREDITS

    region_config = payload.get(region)
    if not region_config or not isinstance(region_config, dict):
        return DEFAULT_FREE_TIER_CREDITS

    team_id_str = str(team_id)
    if team_id_str in region_config:
        try:
            return int(region_config[team_id_str])
        except (ValueError, TypeError):
            return DEFAULT_FREE_TIER_CREDITS

    return DEFAULT_FREE_TIER_CREDITS


def get_ga_launch_date() -> datetime:
    """
    Falls back to DEFAULT_GA_LAUNCH_DATE if not configured.
    """
    payload = _get_billing_config_payload()
    if not payload:
        return DEFAULT_GA_LAUNCH_DATE

    ga_date_str = payload.get("ga_launch_date")
    if not ga_date_str or not isinstance(ga_date_str, str):
        return DEFAULT_GA_LAUNCH_DATE

    try:
        # Parse ISO format date string (YYYY-MM-DD)
        parsed_date = datetime.fromisoformat(ga_date_str)
        # Ensure it has UTC timezone
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=UTC)
        return parsed_date
    except (ValueError, TypeError):
        return DEFAULT_GA_LAUNCH_DATE


def get_conversation_start_time(conversation_id: UUID) -> Optional[datetime]:
    """Get the start time of a conversation."""
    try:
        conversation = Conversation.objects.get(id=conversation_id)
        return conversation.created_at
    except Conversation.DoesNotExist:
        return None


def get_ai_credits(
    team_id: int,
    begin: datetime,
    end: datetime,
    conversation_id: Optional[UUID] = None,
) -> int:
    """
    Calculate AI credits used for a specific team (and optionally a specific conversation) in the given time period.
    """
    # Depending on the region, events are stored in different teams
    # Default to EU (team_id 1) for local dev or unknown regions
    region = get_instance_region()
    region_value = region if region in CLOUD_REGION_TO_TEAM_ID else "EU"
    team_to_query = CLOUD_REGION_TO_TEAM_ID[region_value]

    # Only filter by region in production (EU/US) - local dev events don't have region set
    is_production = region in ["EU", "US"]
    region_filter = "AND JSONExtractString(properties, 'region') = %(region)s" if is_production else ""

    # Session filter expression for PREWHERE (must NOT use alias)
    session_filter_prewhere = (
        "AND JSONExtractString(properties, '$ai_session_id') = %(session_id)s" if conversation_id else ""
    )

    usage_report_kind = "posthog_ai_credits_for_conversation" if conversation_id else "posthog_ai_credits_for_team"

    with tags_context(product=Product.MAX_AI, usage_report=usage_report_kind, kind=usage_report_kind):
        query = f"""
        WITH trace_analysis AS (
            WITH %(excluded_tools)s AS excluded_tools
            SELECT
                trace_id,
                session_id,
                multiIf(
                    length(tool_calls) > 0
                    AND arrayAll(
                        i ->
                            -- tool must be in the excluded list
                            has(excluded_tools, tool_names[i])
                            AND
                            -- if it's search, it must be docs-search
                            if(
                                tool_names[i] = 'search',
                                JSONExtractString(JSONExtractRaw(tool_calls[i], 'args'), 'kind') = 'docs',
                                1
                            ),
                        arrayEnumerate(tool_calls)
                    ),
                    0,  -- all tool calls are excluded → NOT billable
                    1   -- everything else → billable
                ) AS is_billable
            FROM (
                SELECT
                    JSONExtractString(properties, '$ai_trace_id') AS trace_id,
                    JSONExtractString(properties, '$ai_session_id') AS session_id,
                    arrayFlatten(
                        arrayMap(
                            msg -> JSONExtractArrayRaw(msg, 'tool_calls'),
                            -- Only get messages from current turn (after last human message)
                            arraySlice(
                                JSONExtractArrayRaw(
                                    JSONExtractRaw(properties, '$ai_output_state'),
                                    'messages'
                                ),
                                -- Start from the position after the last human message
                                arrayLastIndex(
                                    x -> JSONExtractString(x, 'type') = 'human',
                                    JSONExtractArrayRaw(
                                        JSONExtractRaw(properties, '$ai_output_state'),
                                        'messages'
                                    )
                                ) + 1
                            )
                        )
                    ) AS tool_calls,
                    arrayMap(tc -> JSONExtractString(tc, 'name'), tool_calls) AS tool_names
                FROM events
                PREWHERE
                    team_id = %(team_to_query)s
                    {region_filter}
                    AND timestamp >= %(begin)s
                    AND timestamp < %(end)s
                    AND event = '$ai_trace'
                    {session_filter_prewhere}
            )
        ),
        costs AS (
            SELECT
                customer_team_id,
                trace_id,
                session_id,
                cost_usd
            FROM (
                SELECT
                    JSONExtractInt(properties, 'team_id') AS customer_team_id,
                    JSONExtractString(properties, '$ai_trace_id') AS trace_id,
                    JSONExtractString(properties, '$ai_session_id') AS session_id,
                    toDecimal32OrNull(JSONExtractString(properties, '$ai_total_cost_usd'), 5) AS cost_usd,
                    JSONExtractBool(properties, '$ai_billable') AS ai_billable
                FROM events
                PREWHERE
                    team_id = %(team_to_query)s
                    {region_filter}
                    AND timestamp >= %(begin)s
                    AND timestamp < %(end)s
                    AND event = '$ai_generation'
                    {session_filter_prewhere}
            )
            WHERE
                ai_billable = 1
                AND cost_usd > 0
                AND cost_usd IS NOT NULL
                AND customer_team_id = %(team_id)s
        )
        SELECT toInt64(roundBankers(sum(c.cost_usd * 100 * %(markup_multiplier)s))) AS ai_credits
        FROM costs c
        LEFT JOIN trace_analysis t
            ON c.trace_id = t.trace_id
           AND c.session_id = t.session_id
        WHERE t.is_billable = 1 OR t.trace_id IS NULL
        """

        params = {
            "team_id": team_id,
            "team_to_query": team_to_query,
            "begin": begin,
            "end": end,
            "markup_multiplier": 1 + AI_COST_MARKUP_PERCENT,
            "excluded_tools": AI_BILLING_EXCLUDED_TOOLS,
        }

        if is_production:
            params["region"] = region_value

        if conversation_id:
            params["session_id"] = str(conversation_id)

        results = sync_execute(query, params, workload=Workload.ONLINE, settings=CH_BILLING_SETTINGS)

    if results and results[0][0] is not None:
        return int(results[0][0])
    return 0


def get_ai_credits_for_team(team_id: int, begin: datetime, end: datetime) -> int:
    """Calculate AI credits used for a specific team in the given time period."""
    return get_ai_credits(team_id, begin, end)


def get_ai_credits_for_conversation(team_id: int, conversation_id: UUID, begin: datetime, end: datetime) -> int:
    """Calculate AI credits used for a specific conversation (trace) in the given time period."""
    return get_ai_credits(team_id, begin, end, conversation_id)


def get_past_month_start() -> datetime:
    """
    Get the start of the past month period (30 days ago), capped at GA launch date.
    """
    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)
    ga_launch_date = get_ga_launch_date()
    return max(thirty_days_ago, ga_launch_date)


def format_usage_message(
    conversation_credits: int,
    past_month_credits: int,
    free_tier_credits: int,
    conversation_start: Optional[datetime] = None,
    past_month_start: Optional[datetime] = None,
) -> str:
    """
    Format the usage information into a user-friendly message with a compact layout
    and a simple progress bar against the free tier for the current team_id.
    """
    remaining = free_tier_credits - past_month_credits
    used = past_month_credits

    # Unicode progress bar (20 segments)
    bar_segments = 20
    # Cap fill for the bar at 20; we'll annotate percentage separately (can exceed 100%)
    fill_ratio = 0 if free_tier_credits <= 0 else max(0.0, min(used / free_tier_credits, 1.0))
    filled = int(round(bar_segments * fill_ratio))
    empty = bar_segments - filled
    bar = f"[{'█' * filled}{'░' * empty}]"
    percent = 0 if free_tier_credits <= 0 else (used / free_tier_credits) * 100

    lines: list[str] = [f"## {POSTHOG_AI_USAGE_REPORT_ASSISTANT_MESSAGE_TITLE}", ""]

    # Determine if GA cap is active
    ga_launch_date = get_ga_launch_date()
    ga_cap_active = past_month_start is not None and past_month_start.date() == ga_launch_date.date()
    past_30_label = "**Past 30 days**" + (f" (since {ga_launch_date.strftime('%Y-%m-%d')})" if ga_cap_active else "")

    lines.append(f"**Current conversation**: {conversation_credits:,} credits\n")
    lines.append(f"{past_30_label}: {past_month_credits:,} credits\n")
    lines.append(f"**Free tier limit**: {free_tier_credits:,} credits\n")

    # Progress bar + percent
    if free_tier_credits > 0:
        pct_label = f"{percent:.0f}% of free tier" if percent <= 999 else "999%+ of free tier"
        lines.append(f"**Usage this period**: {bar} {pct_label}\n")

    # Remaining or overage
    if remaining >= 0:
        lines.append(f"**Remaining**: {remaining:,} credits\n")
    else:
        overage = abs(remaining)
        lines.append(f"**Overage**: {overage:,} credits over limit\n")

    # Conversation start (optional context)
    if conversation_start:
        lines.append(f"_Conversation since_: {conversation_start.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n")

    lines.append("")
    lines.append("_Note: Usage data depends on AI trace ingestion and may lag slightly behind real-time activity._")

    # Add GA cap explanation if active
    if ga_cap_active:
        lines.append(
            f"\n_Past 30 days usage is calculated from PostHog AI general availability date ({ga_launch_date.strftime('%b %d, %Y')}) "
            "as usage before this date is not counted._"
        )

    return "\n".join(lines)
