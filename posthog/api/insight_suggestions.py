import json
from typing import Any, Optional, Union

import structlog
from pydantic import BaseModel

from posthog.schema import (
    ActionsNode,
    EventsNode,
    InsightVizNode,
    IntervalType,
    LifecycleQuery,
    NodeKind,
    RetentionEntityKind,
    RetentionPeriod,
    RetentionQuery,
    StickinessQuery,
)

from posthog.hogql.ai import hit_openai

from posthog.models import Team

logger = structlog.get_logger(__name__)


class InsightSuggestion(BaseModel):
    title: str
    description: Optional[str] = None
    targetQuery: InsightVizNode


def get_insight_suggestions(
    query: InsightVizNode, team: Team, insight_result: Optional[dict[str, Any]] = None, context: Optional[str] = None
) -> list[InsightSuggestion]:
    suggestions: list[InsightSuggestion] = []

    if isinstance(query.source, RetentionQuery):
        suggestions.extend(get_retention_suggestions(query.source, query))

    if insight_result:
        suggestions.extend(get_ai_suggestions(query, team, insight_result, context))

    return suggestions


def get_retention_suggestions(query: RetentionQuery, parent_query: InsightVizNode) -> list[InsightSuggestion]:
    retention_filter = query.retentionFilter
    returning_entity = retention_filter.returningEntity

    if not returning_entity:
        return []

    series: list[Union[EventsNode, ActionsNode]] = []
    entity_display_name = "event"

    # Handle Events
    if returning_entity.type == "events" or returning_entity.kind == RetentionEntityKind.EVENTS_NODE:
        event_name = returning_entity.id or returning_entity.name or "event"
        entity_display_name = str(event_name)

        series = [
            EventsNode(
                kind=NodeKind.EVENTS_NODE,
                event=str(event_name) if isinstance(event_name, str) else None,
                name=returning_entity.name,
                custom_name=returning_entity.custom_name,
                properties=returning_entity.properties,
            )
        ]
    # Handle Actions
    elif returning_entity.type == "actions" or returning_entity.kind == RetentionEntityKind.ACTIONS_NODE:
        action_id = int(returning_entity.id) if returning_entity.id else 0
        entity_display_name = returning_entity.name or f"Action {action_id}"

        series = [
            ActionsNode(
                kind=NodeKind.ACTIONS_NODE,
                id=action_id,
                name=returning_entity.name,
                custom_name=returning_entity.custom_name,
                properties=returning_entity.properties,
            )
        ]
    else:
        return []

    # Auto-detect interval
    retention_period = retention_filter.period or RetentionPeriod.DAY
    interval = IntervalType.DAY
    interval_description = "days per week"

    if retention_period == RetentionPeriod.MONTH:
        interval = IntervalType.WEEK
        interval_description = "weeks per month"
    elif retention_period == RetentionPeriod.WEEK:
        interval = IntervalType.DAY
        interval_description = "days per week"
    elif retention_period == RetentionPeriod.HOUR:
        interval = IntervalType.HOUR
        interval_description = "hours per day"

    # Stickiness Query
    stickiness_query = StickinessQuery(
        kind=NodeKind.STICKINESS_QUERY,
        series=series,
        interval=interval,
        dateRange=query.dateRange,
        properties=query.properties,
        filterTestAccounts=query.filterTestAccounts,
        stickinessFilter={},
    )

    stickiness_target = InsightVizNode(
        kind=NodeKind.INSIGHT_VIZ_NODE,
        source=stickiness_query,
    )

    # Lifecycle Query
    lifecycle_query = LifecycleQuery(
        kind=NodeKind.LIFECYCLE_QUERY,
        series=series,
        interval=interval,
        dateRange=query.dateRange,
        properties=query.properties,
        filterTestAccounts=query.filterTestAccounts,
        lifecycleFilter={},
    )

    lifecycle_target = InsightVizNode(
        kind=NodeKind.INSIGHT_VIZ_NODE,
        source=lifecycle_query,
    )

    return [
        InsightSuggestion(
            title=f"Stickiness of users who performed {entity_display_name}",
            description=f"See how frequently retained users perform this event ({interval_description})",
            targetQuery=stickiness_target,
        ),
        InsightSuggestion(
            title=f"Lifecycle of users who perform {entity_display_name}",
            description="See lifecycle of users who perform this event (new vs returning vs resurrecting vs dormant)",
            targetQuery=lifecycle_target,
        ),
    ]


def get_insight_analysis(query: InsightVizNode, team: Team, insight_result: Optional[dict[str, Any]]) -> str:
    """Generate an AI analysis of the insight, highlighting main points and actionable items."""
    try:
        result_summary = json.dumps(insight_result, default=str)[:2000] if insight_result else "No results available"

        prompt = (
            "You are an expert data analyst using PostHog. "
            "Analyze the following insight configuration and its results. "
            "Provide a concise analysis highlighting:\n"
            "1. Main trends or patterns in the data\n"
            "2. Actionable insights or recommendations\n"
            "3. Possible explanations for the observed patterns\n\n"
            "Keep your response focused and actionable. Avoid generic statements.\n\n"
            f"Query Configuration: {query.model_dump_json(exclude_none=True)}\n\n"
            f"Results Summary: {result_summary}"
        )

        messages = [
            {
                "role": "system",
                "content": "You are a helpful data analyst that provides concise, actionable insights about PostHog analytics data.",
            },
            {"role": "user", "content": prompt},
        ]

        content, _, _ = hit_openai(messages, f"team/{team.id}/analysis")
        return content

    except Exception:
        logger.exception("ai_analysis_failed")
        return ""


def get_ai_suggestions(
    query: InsightVizNode, team: Team, insight_result: dict[str, Any], context: Optional[str] = None
) -> list[InsightSuggestion]:
    try:
        context_section = ""
        if context:
            context_section = f"\n\nPrevious Analysis Context:\n{context}\n\nUse this context to generate more relevant and targeted suggestions.\n"

        prompt = (
            "You are an expert data analyst using PostHog. "
            "Given the following analysis configuration and its results, suggest 3 relevant follow-up insights to explore deeper. "
            "The suggestions should help the user understand *why* the results are the way they are, or explore related metrics.\n\n"
            "Important Rules:\n"
            "1. **Schema Compliance**: You must return a valid `InsightVizNode` JSON. \n"
            "   - `TrendsQuery` does NOT have `breakdown` or `display` fields directly.\n"
            "   - Use `breakdownFilter` object for breakdowns (e.g., `breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' }`).\n"
            "   - Use `trendsFilter` object for display (e.g., `trendsFilter: { display: 'ActionsBar' }`).\n"
            "2. **No Hallucination**: Use ONLY event names and property names that appear in the input query. Do not invent new properties like 'user_segment'.\n"
            "3. **Simple Scope**: Focus on changing the visualization type (e.g. Trends, Stickiness), time interval, or breaking down by common properties like '$browser', '$os', '$geoip_country_code' ONLY if you are sure they are relevant. Prefer simple transformations of the existing query.\n\n"
            "Provide the response as a JSON array of objects with the following keys:\n"
            "- title: A short, descriptive title for the suggestion.\n"
            "- description: A brief explanation of why this is interesting.\n"
            "- query_json: A valid PostHog InsightVizNode JSON object that represents the suggested query.\n\n"
            f"Current Query: {query.model_dump_json(exclude_none=True)}\n\n"
            f"Results Summary: {json.dumps(insight_result, default=str)[:2000]}..."
            f"{context_section}"
        )

        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that generates PostHog insights in JSON format. You only return valid JSON arrays.",
            },
            {"role": "user", "content": prompt},
        ]

        content, _, _ = hit_openai(messages, f"team/{team.id}/suggestions")

        # Parse JSON from content
        cleaned_content = content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]

        suggestions_data = json.loads(cleaned_content)

        suggestions = []
        for item in suggestions_data:
            try:
                target_query = InsightVizNode.model_validate(item["query_json"])
                suggestions.append(
                    InsightSuggestion(
                        title=item["title"], description=item.get("description"), targetQuery=target_query
                    )
                )
            except Exception as e:
                logger.warning("invalid_ai_suggestion", error=str(e), suggestion=item)
                continue

        return suggestions

    except Exception:
        logger.exception("ai_suggestions_failed")
        return []
