import xml.etree.ElementTree as ET
from collections.abc import Sequence
from typing import Any, Optional, TypeVar, Union

from jsonref import replace_refs
from langchain_core.messages import (
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    CachedTeamTaxonomyQueryResponse,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MaxEventContext,
    MaxUIContext,
    RetentionQuery,
    TeamTaxonomyQuery,
    TrendsQuery,
    VisualizationMessage,
)

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from ee.hogai.utils.types import AssistantMessageUnion


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def filter_and_merge_messages(
    messages: Sequence[AssistantMessageUnion],
    entity_filter: Union[tuple[type[AssistantMessageUnion], ...], type[AssistantMessageUnion]] = (
        AssistantMessage,
        VisualizationMessage,
    ),
) -> list[AssistantMessageUnion]:
    """
    Filters and merges the message history to be consumable by agents. Returns human and AI messages.
    """
    stack: list[LangchainHumanMessage] = []
    filtered_messages: list[AssistantMessageUnion] = []

    def _merge_stack(stack: list[LangchainHumanMessage]) -> list[HumanMessage]:
        return [
            HumanMessage(content=langchain_message.content, id=langchain_message.id)
            for langchain_message in merge_message_runs(stack)
        ]

    for message in messages:
        if isinstance(message, HumanMessage):
            stack.append(LangchainHumanMessage(content=message.content, id=message.id))
        elif isinstance(message, entity_filter):
            if stack:
                filtered_messages += _merge_stack(stack)
                stack = []
            filtered_messages.append(message)

    if stack:
        filtered_messages += _merge_stack(stack)

    return filtered_messages


T = TypeVar("T", bound=AssistantMessageUnion)


def find_last_message_of_type(messages: Sequence[AssistantMessageUnion], message_type: type[T]) -> Optional[T]:
    return next((msg for msg in reversed(messages) if isinstance(msg, message_type)), None)


def slice_messages_to_conversation_start(
    messages: Sequence[AssistantMessageUnion], start_id: Optional[str] = None
) -> Sequence[AssistantMessageUnion]:
    result = []
    for msg in messages:
        result.append(msg)
        if msg.id == start_id:
            break
    return result


def dereference_schema(schema: dict) -> dict:
    new_schema: dict = replace_refs(schema, proxies=False, lazy_load=False)
    if "$defs" in new_schema:
        new_schema.pop("$defs")
    return new_schema


def find_start_message(messages: Sequence[AssistantMessageUnion], start_id: str | None = None) -> HumanMessage | None:
    for msg in messages:
        if isinstance(msg, HumanMessage) and msg.id == start_id:
            return msg
    return None


def should_output_assistant_message(candidate_message: AssistantMessageUnion) -> bool:
    """
    This is used to filter out messages that are not useful for the user.
    Filter out tool calls without a UI payload and empty assistant messages.
    """
    if isinstance(candidate_message, AssistantToolCallMessage) and candidate_message.ui_payload is None:
        return False

    if isinstance(candidate_message, AssistantMessage) and not candidate_message.content:
        return False

    return True


def find_last_ui_context(messages: Sequence[AssistantMessageUnion]) -> MaxUIContext | None:
    """Returns the last recorded UI context from all messages."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and message.ui_context is not None:
            return message.ui_context
    return None


def _process_events_data(events_in_context: list[MaxEventContext], team: Team) -> tuple[list[dict], dict[str, str]]:
    """Common logic for processing events and building event data."""
    response = TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), team).run(
        ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
    )

    if not isinstance(response, CachedTeamTaxonomyQueryResponse):
        raise ValueError("Failed to generate events prompt.")

    events: list[str] = [
        # Add "All events" to the mapping
        "All events",
    ]
    for item in response.results:
        if len(response.results) > 25 and item.count <= 3:
            continue
        if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(item.event):
            if event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant"):
                continue  # Skip system or ignored events
        events.append(item.event)

    event_to_description: dict[str, str] = {}
    for event in events_in_context:
        if event.name and event.name not in events:
            events.append(event.name)
        if event.name and event.description:
            event_to_description[event.name] = event.description

    # Create a set of event names from context for efficient lookup
    context_event_names = {event.name for event in events_in_context if event.name}

    processed_events = []
    for event_name in events:
        event_data = {"name": event_name}

        if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(event_name):
            # Only skip if it's not in context (context events should always be included)
            if event_name not in context_event_names and (
                event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant")
            ):
                continue  # Skip irrelevant events but keep events the user has added to the context
            if description := event_core_definition.get("description"):
                if label := event_core_definition.get("label_llm") or event_core_definition.get("label"):
                    event_data["description"] = f"{label}. {description}"
                else:
                    event_data["description"] = description
                event_data["description"] = remove_line_breaks(event_data["description"])
        elif event_name in event_to_description:
            event_data["description"] = remove_line_breaks(event_to_description[event_name])

        processed_events.append(event_data)

    return processed_events, event_to_description


def format_events_xml(events_in_context: list[MaxEventContext], team: Team) -> str:
    processed_events, _ = _process_events_data(events_in_context, team)

    root = ET.Element("defined_events")
    for event_data in processed_events:
        event_tag = ET.SubElement(root, "event")
        name_tag = ET.SubElement(event_tag, "name")
        name_tag.text = event_data["name"]
        if "description" in event_data:
            desc_tag = ET.SubElement(event_tag, "description")
            desc_tag.text = event_data["description"]

    return ET.tostring(root, encoding="unicode")


def format_events_yaml(events_in_context: list[MaxEventContext], team: Team) -> str:
    processed_events, _ = _process_events_data(events_in_context, team)

    formatted_events = ["events:"]
    for event_data in processed_events:
        name = event_data["name"]
        description = event_data.get("description", "")
        formatted_events.append(f"- `{name}` - {description}" if description else f"- `{name}`")

    return "\n".join(formatted_events)


def extract_content_from_ai_message(response: BaseMessage) -> str:
    """
    Extracts the content from a BaseMessage, supporting both reasoning and non-reasoning responses.
    """
    if isinstance(response.content, list):
        text_parts = []
        for content_item in response.content:
            if isinstance(content_item, dict):
                if "text" in content_item:
                    text_parts.append(content_item["text"])
                else:
                    raise ValueError(f"LangChain AIMessage with unknown content type: {content_item}")
            elif isinstance(content_item, str):
                text_parts.append(content_item)
        return "".join(text_parts)
    return str(response.content)


def cast_assistant_query(
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery,
) -> TrendsQuery | FunnelsQuery | RetentionQuery | HogQLQuery:
    """
    Convert AssistantQuery types to regular Query types that the frontend expects.
    """
    if query.kind == "TrendsQuery":
        return TrendsQuery(**query.model_dump())
    elif query.kind == "FunnelsQuery":
        return FunnelsQuery(**query.model_dump())
    elif query.kind == "RetentionQuery":
        return RetentionQuery(**query.model_dump())
    elif query.kind == "HogQLQuery":
        return HogQLQuery(**query.model_dump())
    else:
        raise ValueError(f"Unsupported query type: {query.kind}")


def build_insight_url(team: Team, id: str) -> str:
    """Build the URL for an insight."""
    return f"/project/{team.id}/insights/{id}"


def build_dashboard_url(team: Team, id: int) -> str:
    """Build the URL for a dashboard."""
    return f"/project/{team.id}/dashboard/{id}"


def extract_stream_update(update: Any) -> Any:
    if update[1] == "custom":
        # Custom streams come from a tool call
        # If it's a LangGraph-based chunk, we remove the first two elements, which are "custom" and the parent graph namespace
        update = update[2]

    update = update[1:]  # we remove the first element, which is the node/subgraph node name
    return update
