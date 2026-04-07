import json
from typing import Any

import structlog
from pydantic import BaseModel

from posthog.schema import ActorsQuery, FunnelsActorsQuery, InsightActorsQuery, InsightVizNode, StickinessActorsQuery

from posthog.hogql.ai import hit_openai

from posthog.models import Team


class InsightMetadata(BaseModel):
    name: str
    description: str


logger = structlog.get_logger(__name__)


_MATH_LABELS: dict[str, str] = {
    "total": "total count",
    "dau": "unique users",
    "weekly_active": "weekly active users",
    "monthly_active": "monthly active users",
    "unique_session": "unique sessions",
    "first_time_for_user": "first time users",
    "avg_count_per_actor": "avg count per user",
    "min_count_per_actor": "min count per user",
    "max_count_per_actor": "max count per user",
    "median_count_per_actor": "median count per user",
    "avg": "average",
    "sum": "sum",
    "min": "minimum",
    "max": "maximum",
    "median": "median",
    "p90": "p90",
    "p95": "p95",
    "p99": "p99",
    "hogql": "custom expression",
}


def _summarize_series_item(item: Any) -> str:
    """Extract a human-readable summary from a series item (EventsNode, ActionsNode, DataWarehouseNode)."""
    parts: list[str] = []

    # Event or action name
    if hasattr(item, "custom_name") and item.custom_name:
        parts.append(item.custom_name)
    elif hasattr(item, "event") and item.event:
        parts.append(item.event)
    elif hasattr(item, "name") and item.name:
        parts.append(item.name)
    elif hasattr(item, "id") and item.id:
        parts.append(f"Action #{item.id}")
    else:
        parts.append("All events")

    # Math type
    if hasattr(item, "math") and item.math:
        math_str = str(item.math)
        label = _MATH_LABELS.get(math_str, math_str)
        parts.append(f"({label})")

        # Math property
        if hasattr(item, "math_property") and item.math_property:
            parts.append(f"of {item.math_property}")

    return " ".join(parts)


def summarize_query_for_naming(query: InsightVizNode, team: Team | None = None) -> str:
    """Extract only the fields that matter for naming an insight into a compact summary."""
    source = query.source
    if not source:
        return "Unknown query"

    lines: list[str] = []
    lines.append(f"Type: {source.kind}")

    # Series (Trends, Funnels, Stickiness, Lifecycle)
    if hasattr(source, "series") and source.series:
        series_summaries = [_summarize_series_item(item) for item in source.series]
        if source.kind == "FunnelsQuery":
            lines.append(f"Funnel steps: {' → '.join(series_summaries)}")
        else:
            lines.append(f"Series: {', '.join(series_summaries)}")

    # Interval
    if hasattr(source, "interval") and source.interval:
        lines.append(f"Interval: {source.interval}")

    # Breakdown
    if hasattr(source, "breakdownFilter") and source.breakdownFilter:
        bf = source.breakdownFilter
        if bf.breakdown:
            lines.append(f"Breakdown: {bf.breakdown}")
        if bf.breakdowns:
            breakdown_strs = [str(b.property) if hasattr(b, "property") else str(b) for b in bf.breakdowns]
            lines.append(f"Breakdowns: {', '.join(breakdown_strs)}")

    # Retention-specific
    if hasattr(source, "retentionFilter") and source.retentionFilter:
        rf = source.retentionFilter
        if rf.returningEntity:
            entity = rf.returningEntity
            entity_name = entity.custom_name or entity.name or entity.id or "event"
            lines.append(f"Returning event: {entity_name}")
        if rf.targetEntity:
            entity = rf.targetEntity
            entity_name = entity.custom_name or entity.name or entity.id or "event"
            lines.append(f"Target event: {entity_name}")
        if rf.period:
            lines.append(f"Period: {rf.period}")
    # Paths-specific
    if hasattr(source, "pathsFilter") and source.pathsFilter:
        pf = source.pathsFilter
        if pf.includeEventTypes:
            lines.append(f"Path type: {', '.join(str(t) for t in pf.includeEventTypes)}")
        if pf.startPoint:
            lines.append(f"Start point: {pf.startPoint}")
        if pf.endPoint:
            lines.append(f"End point: {pf.endPoint}")

    # Aggregation group
    if hasattr(source, "aggregation_group_type_index") and source.aggregation_group_type_index is not None:
        group_label = (
            _resolve_group_type_name(team, source.aggregation_group_type_index)
            if team
            else f"group type {source.aggregation_group_type_index}"
        )
        lines.append(f"Aggregating by: {group_label}")

    return "\n".join(lines)


_NAMING_GUIDANCE: dict[str, str] = {
    "TrendsQuery": (
        "This is a TRENDS insight — a metric (or several) plotted over time.\n"
        "1 series  → just name the metric: 'Daily Pageviews', 'Weekly Active Users'\n"
        "2-6 series → list all with commas + 'and': 'Pageviews, Pageleaves, and Insight Created'\n"
        "6+ series → list primary metric then 'and other key metrics': 'Pageviews and other key metrics'\n"
        "If the aggregation is notable (unique users, avg per user), weave it in naturally: "
        "'Unique Users', 'Avg Session Duration'"
    ),
    "FunnelsQuery": (
        "This is a FUNNEL insight — a conversion path through ordered steps.\n"
        "Use arrows between the first and last step: 'Signup → Purchase Conversion'\n"
        "For long funnels (4+ steps), use only the entry and exit: 'Landing → Checkout Conversion'\n"
        "Never use 'vs' for funnels. End with 'Conversion' or 'Funnel'."
    ),
    "RetentionQuery": (
        "This is a RETENTION insight — tracks how many users return after an initial event.\n"
        "Omit internal details like first occurrence or filters.\n"
        "If the period is non-default, lead with it: 'Weekly Retention after Signup'.\n"
        "If the target and returning events differ, include both: 'Retention: Signup → Feature Use'."
    ),
    "StickinessQuery": (
        "This is a STICKINESS insight — how many days/weeks users performed an event.\n"
        "Focus on the event and engagement: 'Dashboard Stickiness', 'Feature Use Frequency'"
    ),
    "LifecycleQuery": (
        "This is a LIFECYCLE insight — new, returning, resurrecting, and dormant users.\n"
        "Name the event being tracked: 'Pageview Lifecycle', 'Signup Lifecycle'"
    ),
    "PathsQuery": (
        "This is a PATHS insight — visualizes the sequences of pages, screens, or events users take.\n"
        "Use short labels for path types: '$pageview' → 'Page', '$screen' → 'Screen', 'custom_event' → 'Event'.\n"
        "Combine multiple types with '&': 'Page & Screen Paths'.\n"
        "If a start/end point is a URL, extract just the meaningful path segment for the name "
        "(e.g. 'http://example.com/project/1/insights' → 'Insights Page').\n"
        "If a start/end point is an event name, humanize it normally.\n"
        "Examples: 'User Page Paths', 'Page & Screen Paths', 'Page Paths from Insights'"
    ),
}


def generate_insight_metadata(query: InsightVizNode | ActorsQuery, team: Team) -> InsightMetadata:
    """Generate a concise name and description for an insight based on its query configuration."""
    if isinstance(query, ActorsQuery):
        return _generate_actors_metadata(query, team)

    return _generate_insight_viz_metadata(query, team)


SupportedActorSource = InsightActorsQuery | FunnelsActorsQuery | StickinessActorsQuery
SUPPORTED_ACTOR_SOURCES = (InsightActorsQuery, FunnelsActorsQuery, StickinessActorsQuery)


def _generate_actors_metadata(query: ActorsQuery, team: Team) -> InsightMetadata:
    actor_source = query.source
    assert isinstance(actor_source, SUPPORTED_ACTOR_SOURCES)
    inner_source = _narrow_to_selected_series(actor_source, actor_source.source)
    query_kind = inner_source.kind
    insight_guidance = _NAMING_GUIDANCE.get(query_kind, "")

    viz_query = InsightVizNode(kind="InsightVizNode", source=inner_source)
    actors_context = _summarize_actors_context(actor_source, inner_source, team)
    query_summary = f"Actors view for:\n{summarize_query_for_naming(viz_query, team)}\n{actors_context}"
    type_guidance = (
        f"This is an ACTORS view — a table listing individual persons, groups, or sessions matching an insight's criteria.\n"
        f"The underlying insight is a {query_kind}. {insight_guidance}\n"
        f"Name it as a natural phrase starting with the actor type:\n"
        f"- Persons: 'Persons Who Performed Pageviews', 'Persons Who Converted: Signup → Purchase'\n"
        f"- Groups: 'Organizations Who Performed Pageviews' (use the group type name)\n"
        f"- Sessions: 'Sessions with Pageviews'\n"
        f"If there is a lifecycle status, lead with it: 'Resurrecting Persons on Pageviews', 'New Persons on Signups'.\n"
        f"If there is a funnel step, include it: 'Persons Who Converted at Step 2: Signup → Purchase', "
        f"'Persons Who Dropped Off at Step 3: Signup → Purchase'.\n"
        f"For the description, explain what list of actors this shows and the specific filter criteria."
    )

    return _request_metadata_from_llm(query_summary, type_guidance, team)


def _narrow_to_selected_series(
    actor_source: InsightActorsQuery | FunnelsActorsQuery | StickinessActorsQuery, inner_source: Any
) -> Any:
    """If the actor query targets a specific series, return a copy with only that series."""
    series_index = getattr(actor_source, "series", None)
    if series_index is not None and hasattr(inner_source, "series") and inner_source.series:
        if 0 <= series_index < len(inner_source.series):
            return inner_source.model_copy(update={"series": [inner_source.series[series_index]]})
    return inner_source


def _summarize_actors_context(
    actor_source: InsightActorsQuery | FunnelsActorsQuery | StickinessActorsQuery, inner_source: Any, team: Team
) -> str:
    """Extract actors-specific context like lifecycle status, funnel step, breakdown value."""
    lines: list[str] = []

    actor_type = _detect_actor_type(actor_source, inner_source, team)
    lines.append(f"Actor type: {actor_type}")

    # Lifecycle status
    if isinstance(actor_source, InsightActorsQuery) and actor_source.status:
        lines.append(f"Lifecycle status: {actor_source.status}")

    # Funnel step
    if isinstance(actor_source, FunnelsActorsQuery) and actor_source.funnelStep is not None:
        step = actor_source.funnelStep
        step_index = abs(step) - 1
        step_name = None
        if hasattr(inner_source, "series") and inner_source.series and 0 <= step_index < len(inner_source.series):
            step_name = _summarize_series_item(inner_source.series[step_index])
        step_label = f"step {abs(step)}" + (f" ({step_name})" if step_name else "")
        if step > 0:
            lines.append(f"Converted at {step_label}")
        else:
            lines.append(f"Dropped off at {step_label}")

    # Stickiness day bucket
    day = getattr(actor_source, "day", None)
    if day is not None and inner_source.kind == "StickinessQuery":
        lines.append(f"Stickiness bucket: {day} days")

    # Breakdown value filter
    breakdown_value = getattr(actor_source, "breakdown", None) or getattr(actor_source, "funnelStepBreakdown", None)
    if breakdown_value is not None:
        breakdown_prop = None
        if hasattr(inner_source, "breakdownFilter") and inner_source.breakdownFilter:
            breakdown_prop = inner_source.breakdownFilter.breakdown
        if breakdown_prop:
            lines.append(f"Filtered to breakdown {breakdown_prop} = {breakdown_value}")
        else:
            lines.append(f"Filtered to breakdown value: {breakdown_value}")

    return "\n".join(lines)


def _detect_actor_type(
    actor_source: InsightActorsQuery | FunnelsActorsQuery | StickinessActorsQuery, inner_source: Any, team: Team
) -> str:
    """Determine the actor type label: 'persons', 'sessions', or a group name."""
    # Groups
    if hasattr(inner_source, "aggregation_group_type_index") and inner_source.aggregation_group_type_index is not None:
        return _resolve_group_type_name(team, inner_source.aggregation_group_type_index)

    # Sessions via funnel HogQL aggregation
    if hasattr(inner_source, "funnelsFilter") and inner_source.funnelsFilter:
        hogql_agg = getattr(inner_source.funnelsFilter, "funnelAggregateByHogQL", None)
        if hogql_agg and "session_id" in str(hogql_agg):
            return "sessions"

    # Sessions via series math
    if hasattr(inner_source, "series") and inner_source.series:
        series_index = getattr(actor_source, "series", None)
        selected = (
            inner_source.series[series_index]
            if series_index is not None and 0 <= series_index < len(inner_source.series)
            else inner_source.series[0]
        )
        if hasattr(selected, "math") and selected.math == "unique_session":
            return "sessions"

    return "persons"


def _resolve_group_type_name(team: Team, group_type_index: int) -> str:
    from posthog.models.group_type_mapping import GroupTypeMapping

    try:
        mapping = GroupTypeMapping.objects.get(team=team, group_type_index=group_type_index)
        return mapping.name_plural or mapping.name_singular or mapping.group_type
    except GroupTypeMapping.DoesNotExist:
        return f"group type {group_type_index}"


def _generate_insight_viz_metadata(query: InsightVizNode, team: Team) -> InsightMetadata:
    query_summary = summarize_query_for_naming(query, team)
    query_kind = query.source.kind if query.source else "Unknown"
    type_guidance = _NAMING_GUIDANCE.get(query_kind, "")

    return _request_metadata_from_llm(query_summary, type_guidance, team)


def _request_metadata_from_llm(query_summary: str, type_guidance: str, team: Team) -> InsightMetadata:
    try:
        prompt = (
            "Name and describe this product analytics insight for a dashboard. "
            "Optimize for clarity and scanability — a teammate should instantly understand "
            "what this insight tracks at a glance.\n\n"
            f"{type_guidance}\n\n"
            "Rules for the NAME:\n"
            "- Title case (e.g. 'Pageviews, Pageleaves')\n"
            "- 3-12 words — use as many as needed to capture all series and breakdowns\n"
            "- Humanize event names: '$pageview' → 'Pageviews', 'user_signed_up' → 'Signups'\n"
            "- Include 'by <dimension>' only when a breakdown is present. Multiple breakdowns - join with 'and': 'by Browser and OS'\n"
            "- Drop filler words: 'count', 'total', 'events', 'data', 'trend'\n"
            "- If math is just total count, omit it — it's the default\n\n"
            "Rules for the DESCRIPTION:\n"
            "- One short sentence — what this insight measures\n"
            "- Plain language, no jargon\n\n"
            "Query:\n"
            f"{query_summary}\n\n"
            'Return ONLY a JSON object: {"name": "...", "description": "..."}'
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that generates insight names and descriptions. "
                    "Return only a JSON object with 'name' and 'description' keys, nothing else."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        content, _, _ = hit_openai(
            messages,
            f"team/{team.id}/generate-insight-metadata",
            posthog_properties={
                "ai_product": "product_analytics",
                "ai_feature": "insight-ai-metadata-generation",
            },
        )

        parsed = json.loads(content.strip())
        name = parsed["name"].strip().strip('"').strip("'")
        description = parsed["description"].strip()

        if len(name) > 100:
            name = name[:97] + "..."
        if len(description) > 200:
            description = description[:197] + "..."

        return InsightMetadata(name=name, description=description)

    except Exception:
        logger.exception("ai_metadata_generation_failed")
        raise
