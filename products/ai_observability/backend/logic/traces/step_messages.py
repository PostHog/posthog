import re
from collections.abc import Iterator, Sequence

from ...facade import contracts
from ..message_normalizer.errors import RecipeRuntimeError
from ..message_normalizer.roles import AVAILABLE_TOOLS_ROLE, THINKING_ROLE, TOOL_RESULT_ROLE
from ..message_normalizer.run_limits import OUTPUT_NODES_PER_CLOCK_CHECK, check_time_limit, execution_budget
from ..message_normalizer.values import CompatMessage, JsonValue, charge_kept_parse, parse_json_text
from .attachments import is_attachment_item_type, to_attachment
from .json_numbers import has_lossy_number

_TEXT_ITEM_TYPES = frozenset({"text", "input_text", "output_text"})

# Pydantic cannot serialize values nested much deeper than this, and one such value would fail the whole response.
_MAX_TOOL_VALUE_DEPTH = 200

# The response renderer, orjson, encodes no integer outside this range and no string that holds a surrogate code point.
_RENDERABLE_INTEGERS = range(-(2**63), 2**64)
_SURROGATE = re.compile("[\ud800-\udfff]")


type _CallKey = tuple[int, int]


class UnrenderableValueError(RecipeRuntimeError):
    pass


def to_messages(
    compat: Sequence[CompatMessage], *, id_prefix: str, source_node_id: str | None, team_id: int
) -> list[contracts.TraceMessage]:
    # The engine's budget closes when its run returns, so the parses that build the messages charge a budget of their
    # own. The caller's deadline still applies, because each parse and each budget charge checks the clock.
    with execution_budget():
        return _messages(compat, id_prefix=id_prefix, source_node_id=source_node_id, team_id=team_id)


def _messages(
    compat: Sequence[CompatMessage], *, id_prefix: str, source_node_id: str | None, team_id: int
) -> list[contracts.TraceMessage]:
    contents = [_content_parts(message, team_id) for message in compat]
    results, folded = _fold_results(compat, contents)
    messages: list[contracts.TraceMessage] = []

    for index, message in enumerate(compat):
        if index in folded or message.get("role") == AVAILABLE_TOOLS_ROLE:
            continue
        role = _to_role(message.get("role"))
        text, attachments = contents[index]
        parts: list[contracts.TraceMessagePart] = []
        if text:
            if message.get("role") == THINKING_ROLE:
                parts.append(contracts.TraceThinkingPart(kind="thinking", text=_renderable_text(text)))
            else:
                parts.append(contracts.TraceTextPart(kind="text", text=_renderable_text(text)))
        parts.extend(attachments)
        for position, raw_call in enumerate(_list_of_mappings(message.get("tool_calls"))):
            function = raw_call.get("function")
            function = function if isinstance(function, dict) else {}
            name = function.get("name")
            parts.append(
                contracts.TraceToolCallPart(
                    kind="toolCall",
                    name=_renderable_text(name) if isinstance(name, str) else "",
                    args=_tool_value(function.get("arguments")),
                    result=results.get((index, position)),
                )
            )
        if not parts:
            continue
        messages.append(
            contracts.TraceMessage(
                id=f"{id_prefix}-{index}",
                role=role,
                parts=parts,
                is_internal=role == "tool" or all(part.kind in ("thinking", "toolCall") for part in parts),
                source_node_id=source_node_id,
            )
        )
    return messages


def _fold_results(
    compat: Sequence[CompatMessage], contents: Sequence[tuple[str, list[contracts.TraceAttachmentPart]]]
) -> tuple[dict[_CallKey, JsonValue], set[int]]:
    pending: dict[str, _CallKey] = {}
    results: dict[_CallKey, JsonValue] = {}
    folded: set[int] = set()
    for index, message in enumerate(compat):
        if message.get("role") == AVAILABLE_TOOLS_ROLE:
            continue
        text, attachments = contents[index]
        tool_call_id = message.get("tool_call_id")
        # A tool call part cannot hold attachments, so a result carrying media stays its own message.
        if (
            _to_role(message.get("role")) == "tool"
            and isinstance(tool_call_id, str)
            and tool_call_id
            and not attachments
        ):
            if tool_call_id in pending:
                results[pending.pop(tool_call_id)] = _parse_tool_result(text or message.get("content"))
                folded.add(index)
                continue
        for position, raw_call in enumerate(_list_of_mappings(message.get("tool_calls"))):
            call_id = raw_call.get("id")
            if isinstance(call_id, str) and call_id:
                pending[call_id] = (index, position)
    return results, folded


def _to_role(role: JsonValue) -> contracts.TraceMessageRole:
    if role == "developer" or role == "system":
        return "system"
    if role == "user":
        return "user"
    if role == "tool" or role == TOOL_RESULT_ROLE:
        return "tool"
    return "assistant"


def _list_of_mappings(value: JsonValue) -> list[dict[str, JsonValue]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _content_item(item: JsonValue) -> dict[str, JsonValue] | None:
    return item if isinstance(item, dict) and isinstance(item.get("type"), str) else None


def _parse_json_text(text: str) -> JsonValue:
    try:
        parsed = parse_json_text(text)
    except ValueError:
        return text
    return parsed if _renders(parsed) else text


def _tool_value(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        parsed = _parse_json_text(value)
        if parsed is not value:
            charge_kept_parse(value, parsed)
        return parsed
    # Text the response cannot hold stays text, but a value the engine already parsed has no text to fall back to.
    if not _renders(value):
        raise UnrenderableValueError(
            f"A tool call value nests deeper than {_MAX_TOOL_VALUE_DEPTH} levels or holds a value the response cannot encode"
        )
    return value


def _renderable_text(text: str) -> str:
    if _SURROGATE.search(text):
        raise UnrenderableValueError("A message holds text the response cannot encode")
    return text


def _renderable_attachment(part: contracts.TraceAttachmentPart) -> contracts.TraceAttachmentPart:
    for text in (part.name, part.mime_type, part.url):
        if text is not None:
            _renderable_text(text)
    return part


def _renders(value: JsonValue) -> bool:
    # The walk holds one child iterator per open container, so its memory follows the depth of the value, not its
    # width. It visits values that no budget has charged yet, so it checks the clock itself.
    if not _node_renders(value):
        return False
    open_containers = [_children(value)]
    visited = 0
    while open_containers:
        for child in open_containers[-1]:
            visited += 1
            if visited % OUTPUT_NODES_PER_CLOCK_CHECK == 0:
                check_time_limit()
            if not _node_renders(child):
                return False
            if isinstance(child, dict | list):
                if len(open_containers) == _MAX_TOOL_VALUE_DEPTH:
                    return False
                open_containers.append(_children(child))
                break
        else:
            open_containers.pop()
    return True


def _node_renders(node: JsonValue) -> bool:
    if isinstance(node, dict):
        return not any(_SURROGATE.search(key) for key in node)
    if isinstance(node, str):
        return not _SURROGATE.search(node)
    if isinstance(node, int):
        return node in _RENDERABLE_INTEGERS
    return True


def _children(node: JsonValue) -> Iterator[JsonValue]:
    if isinstance(node, dict):
        return iter(node.values())
    return iter(node) if isinstance(node, list) else iter(())


def _parse_tool_result(result: JsonValue) -> JsonValue:
    parsed = _tool_value(result)
    if not isinstance(parsed, dict | list):
        return result
    # The browser parses this response, so a number it would round keeps the result as its exact text. The scan runs
    # on valid JSON only, because its string pattern rescans the rest of malformed text from every unclosed quote.
    return result if isinstance(result, str) and has_lossy_number(result) else parsed


def _parse_media_item(content: str) -> dict[str, JsonValue] | None:
    if not content.startswith("{"):
        return None
    item = _content_item(_parse_json_text(content))
    if not item or not is_attachment_item_type(str(item["type"])):
        return None
    charge_kept_parse(content, item)
    return item


def _item_text(item: JsonValue) -> str | None:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if isinstance(item_type, str) and item_type in _TEXT_ITEM_TYPES and isinstance(item.get("text"), str):
        return str(item["text"])
    if item_type == "text" and isinstance(item.get("content"), str):
        return str(item["content"])
    return None


def _content_text(message: CompatMessage) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(text for item in content if (text := _item_text(item)) is not None)
    if isinstance(content, dict) and isinstance(content.get("content"), str):
        return str(content["content"])
    return ""


def _side_channel_texts(message: CompatMessage) -> list[str]:
    audio = message.get("audio")
    transcript = audio.get("transcript") if isinstance(audio, dict) else None
    return [text for text in (message.get("refusal"), transcript) if isinstance(text, str) and text != ""]


def _message_text(message: CompatMessage) -> str:
    return "\n".join(text for text in (_content_text(message), *_side_channel_texts(message)) if text != "")


def _content_parts(message: CompatMessage, team_id: int) -> tuple[str, list[contracts.TraceAttachmentPart]]:
    content = message.get("content")
    media_item = _parse_media_item(content) if isinstance(content, str) else None
    if media_item:
        return "", [_renderable_attachment(to_attachment(media_item, team_id))]
    items = content if isinstance(content, list) else []
    attachments = [
        _renderable_attachment(to_attachment(item, team_id))
        for raw in items
        if (item := _content_item(raw)) and item["type"] not in _TEXT_ITEM_TYPES
    ]
    return _message_text(message), attachments
