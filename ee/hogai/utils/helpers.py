import json
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from typing import Any, Optional, TypeVar, Union, cast
from urllib.parse import urlparse
from uuid import uuid4

from jsonref import replace_refs
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantMessageMetadata,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    CachedTeamTaxonomyQueryResponse,
    ContextMessage,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MaxEventContext,
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
from ee.hogai.utils.types.base import AssistantDispatcherEvent


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


def find_start_message_idx(messages: Sequence[AssistantMessageUnion], start_id: str | None = None) -> int:
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if isinstance(msg, HumanMessage) and msg.id == start_id:
            return idx
    return 0


def find_start_message(messages: Sequence[AssistantMessageUnion], start_id: str | None = None) -> HumanMessage | None:
    if not messages:
        return None
    index = find_start_message_idx(messages, start_id)
    return cast(HumanMessage, messages[index])


def should_output_assistant_message(candidate_message: AssistantMessageUnion) -> bool:
    """
    This is used to filter out messages that are not useful for the user.
    Filter out empty assistant messages and context messages.
    """
    if isinstance(candidate_message, AssistantMessage):
        if (
            (candidate_message.tool_calls is None or len(candidate_message.tool_calls) == 0)
            and len(candidate_message.content) == 0
            and candidate_message.meta is None
        ):
            # Empty assistant message
            return False

    # Filter out context messages
    if isinstance(candidate_message, ContextMessage):
        return False

    return True


def convert_tool_messages_to_dict(messages: Sequence[AssistantMessageUnion]) -> Mapping[str, AssistantToolCallMessage]:
    """Converts `AssistantToolCallMessage` messages to a dictionary mapping tool call id to message."""
    return {message.tool_call_id: message for message in messages if isinstance(message, AssistantToolCallMessage)}


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
        text_parts: list[str] = []
        for content_item in response.content:
            if isinstance(content_item, dict) and "type" in content_item and content_item["type"] == "text":
                text_parts.append(content_item["text"])
            elif isinstance(content_item, str):
                text_parts.append(content_item)
        return "".join(text_parts)
    return str(response.content)


def extract_thinking_from_ai_message(response: BaseMessage) -> list[dict[str, Any]]:
    thinking: list[dict[str, Any]] = []

    for content in response.content:
        # Anthropic style reasoning
        if isinstance(content, dict) and "type" in content:
            if content["type"] in ("thinking", "redacted_thinking"):
                thinking.append(content)
    if response.additional_kwargs.get("reasoning") and (
        summary := response.additional_kwargs["reasoning"].get("summary")
    ):
        # OpenAI style reasoning
        thinking.append(
            {
                "type": "thinking",
                "thinking": summary[0]["text"],
            }
        )
    return thinking


def normalize_ai_message(message: AIMessage | AIMessageChunk) -> list[AssistantMessage]:
    _create_blank_assistant_message = lambda: AssistantMessage(
        content="",
        id=None if isinstance(message, AIMessageChunk) else str(uuid4()),
        tool_calls=[],
        server_tool_calls=[],
        meta=AssistantMessageMetadata(thinking=[]),
    )
    if isinstance(message.content, list):
        messages: list[AssistantMessage] = [_create_blank_assistant_message()]
        for content_item in message.content:
            if messages[-1].server_tool_calls:
                # Server tool use necessisates starting a new AssistantMessage for correct presentation
                messages.append(_create_blank_assistant_message())
            if isinstance(content_item, dict) and "type" in content_item:
                if content_item["type"] == "text":
                    if "text" in content_item:
                        messages[-1].content += content_item["text"]
                    if "citations" in content_item:
                        messages[-1].content += "".join(
                            f" [({urlparse(citation['url']).netloc})]({citation['url']})"  # Must have space in front
                            for citation in content_item["citations"]
                        )
                if content_item["type"] in ("thinking", "redacted_thinking"):
                    messages[-1].meta.thinking.append(content_item)
                if content_item["type"] == "server_tool_use":
                    try:
                        args_parsed = json.loads(content_item["partial_json"])  # Not provided by LangChain
                    except (KeyError, json.JSONDecodeError):
                        args_parsed = {}
                    messages[-1].server_tool_calls.append(
                        AssistantToolCall(
                            id=content_item["id"],
                            name=content_item["name"],
                            args=args_parsed,
                        )
                    )
            elif isinstance(content_item, str):
                messages[-1].content += content_item
    else:
        content = extract_content_from_ai_message(message)
        thinking = extract_thinking_from_ai_message(message)
        messages = [
            AssistantMessage(
                id=None if isinstance(message, AIMessageChunk) else str(uuid4()),
                content=content,
                meta=AssistantMessageMetadata(thinking=thinking) if thinking else None,
            )
        ]

    # Regular tool calls are added separately to the last message, as their args must be fully complete to be JSON-valid
    if isinstance(message, AIMessageChunk):
        tool_calls = [
            AssistantToolCall(
                id=tool_call["id"],
                name=tool_call["name"],
                args=(tool_call["args"] if isinstance(tool_call["args"], dict) else {}),
            )
            for tool_call in message.tool_call_chunks
            if tool_call["id"] is not None and tool_call["name"] is not None
        ]
    else:
        tool_calls = [
            AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"] or {})
            for tool_call in message.tool_calls
        ]
    messages[-1].tool_calls = tool_calls

    return messages


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
    # Handle old LangGraph tuple format
    if update[1] == "custom":
        # Custom streams come from a tool call
        # If it's a LangGraph-based chunk, we remove the first two elements, which are "custom" and the parent graph namespace
        update = update[2]

    if isinstance(update, AssistantDispatcherEvent):
        return update

    update = update[1:]  # we remove the first element, which is the node/subgraph node name
    return update


def insert_messages_before_start(
    messages: Sequence[AssistantMessageUnion],
    new_messages: Sequence[AssistantMessageUnion],
    start_id: str | None = None,
) -> list[AssistantMessageUnion]:
    # Insert context messages right before the start message
    start_idx = find_start_message_idx(messages, start_id)
    return [*messages[:start_idx], *new_messages, *messages[start_idx:]]
