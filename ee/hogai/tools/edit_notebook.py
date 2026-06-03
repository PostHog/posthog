import copy
import uuid
import asyncio
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self, cast

from django.utils.timezone import now

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, model_validator

from posthog.schema import AssistantTool, MaxNotebookContext, MaxNotebookRequestLocationContext, MaxUIContext

from posthog.models import Team, User
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from products.notebooks.backend.collab import submit_steps
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.python_analysis import annotate_python_nodes

from ee.hogai.artifacts.types import VisualizationRefBlock
from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.create_notebook.parsing import parse_notebook_content_for_storage
from ee.hogai.tools.create_notebook.tiptap import (
    EXECUTABLE_ANALYSIS_NODE_TYPES,
    blocks_to_tiptap_doc,
    content_uses_executable_analysis_blocks,
    markdown_to_tiptap_nodes,
    nodes_use_executable_analysis_blocks,
    tiptap_doc_to_text,
)
from ee.hogai.utils.feature_flags import has_notebook_python_feature_flag
from ee.hogai.utils.types.base import AssistantState, NodePath

try:
    from products.posthog_ai.backend.models.assistant import AgentArtifact
except ModuleNotFoundError:
    from ee.models.assistant import AgentArtifact

_EDIT_NOTEBOOK_QUERY_NODE_GUIDANCE = """
# Inserting query nodes
Markdown `content` supports `<query title="...">{...query JSON...}</query>` for inline query visualization nodes, including old-style HogQLQuery nodes.
""".strip()

_EDIT_NOTEBOOK_EXECUTABLE_ANALYSIS_GUIDANCE = """
# Inserting analysis cells
Prefer `<query title="...">{...query JSON...}</query>` blocks containing HogQLQuery or InsightVizNode query JSON for SQL analysis today.
Markdown `content` also supports executable notebook cells when the user specifically needs Python, DuckDB, or executable cells:
- `<hogql title="..." return_variable="events_df">SELECT ...</hogql>` for HogQL SQL cells.
- `<ducksql title="..." return_variable="summary_df">SELECT ...</ducksql>` for DuckDB SQL cells.
- `<python title="...">print(events_df)</python>` for Python cells.
- `<query title="...">{...query JSON...}</query>` for inline query visualization nodes.
""".strip()


def build_edit_notebook_prompt(*, allow_executable_analysis_blocks: bool) -> str:
    content_guidance = (
        _EDIT_NOTEBOOK_EXECUTABLE_ANALYSIS_GUIDANCE
        if allow_executable_analysis_blocks
        else _EDIT_NOTEBOOK_QUERY_NODE_GUIDANCE
    )

    return f"""
Use this tool to edit an existing saved notebook. Prefer it whenever the user asks you to change, update, append to, or replace content in a notebook they are viewing or have referenced.

This tool applies anchored edits to the latest notebook content through the same collaboration save path used by the notebook editor. Open notebook pages receive the change live.

# When to use this instead of create_notebook
- The user asks to modify an existing notebook.
- The user asks to replace a placeholder block in the current notebook.
- Notebook context contains instructions like "replace this block", "add an insight here", or "fill this in".
- You created an insight and now need to place it into the notebook.

# Targeting notebooks
- If the user is viewing a notebook, you may omit `short_id`; the current notebook from UI context will be used.
- If multiple notebooks are in context, provide the exact `short_id`.

# Inserting insights
Use `<insight>artifact_id</insight>` in `content` to insert a visualization artifact created earlier in the conversation.

{content_guidance}

# Notebook request locations and AI placeholders
- Notebook context may include a `Request location` block. This is the exact place where the user invoked PostHog AI.
- If the user's message says "here", "there", "this spot", "this place", "at this location", "where I typed /ai", or any similar location language, it refers to the `Request location`.
- If `Current block text` is an `<AI id="...">Thinking...</AI>` tag, it is the notebook's visible `Thinking...` placeholder. Use `replace_block` with that exact tag as the `anchor`.
- If there is a request location but no current placeholder tag, insert at that location using `insert_between` with the previous and next block texts, or `insert_after` / `insert_before` when only one side is available.
- Do not use `append` when a request location is present unless the user explicitly asked to add content to the end of the notebook.
- Nearby headings and notebook sections are context. They are not the target unless the user's request specifically names them as the target.
- Do not relocate the edit to a semantically related section elsewhere in the notebook. For example, if the user types `/ai drop a dad joke here` in the middle of the notebook, add the joke at the `Request location` / `<AI ...>Thinking...</AI>` placeholder, not at an existing dad-joke section and not at the end.

Example:
{{
  "edits": [
    {{
      "type": "replace_block",
      "anchor": "<AI id=\"placeholder-123\">Thinking...</AI>",
      "content": "The content the user asked to add here"
    }}
  ]
}}

# Edit operations
- `replace_block`: replace the whole top-level notebook block containing exact anchor text. Use this for placeholders.
- `insert_after`, `insert_before`, `insert_after_heading`, `insert_between`: insert content around exact text anchors.
- `append`: add content to the end of the notebook.
- `replace_text`: replace exact text within normal text and inside query/code node attributes. For small SQL edits like changing `LIMIT 25` to `LIMIT 200`, prefer `replace_text` with `anchor` set to the query title or section heading; do not rebuild the whole query block.

Use exact anchors copied from notebook context. When the anchor is a heading, `replace_text` searches that heading section until the next same-or-higher-level heading. Do not use create_notebook to edit a saved notebook.
""".strip()


EDIT_NOTEBOOK_PROMPT = build_edit_notebook_prompt(allow_executable_analysis_blocks=False)


ProseMirrorNode = dict[str, Any]
ProseMirrorDoc = dict[str, Any]
ReplaceStep = dict[str, Any]

LEAF_NODE_TYPES = {"hardBreak", "horizontalRule"}
MAX_TEXT_REPLACEMENTS = 100
AI_PLACEHOLDER_PREFIX = "<AI"
AI_PLACEHOLDER_SUFFIX = "</AI>"
EXECUTABLE_ANALYSIS_BLOCK_ERROR = (
    "Error: Python, HogQL SQL, and DuckDB SQL notebook cells require the notebook-python feature flag. "
    "Use <query> nodes or <insight> artifacts instead."
)


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def code_point_index_for_utf16_offset(value: str, offset: int) -> int:
    if offset <= 0:
        return 0

    utf16_position = 0
    for index, char in enumerate(value):
        if utf16_position >= offset:
            return index
        utf16_position += utf16_length(char)
    return len(value)


class InsertContentArgs(BaseModel):
    content: str | None = Field(
        default=None,
        description=(
            "Text or simple Markdown to insert. Supports <insight>artifact_id</insight> tags for visualization "
            "artifacts and <query> blocks for inline query visualization nodes. "
            "Provide either content or nodes, not both."
        ),
    )
    content_format: Literal["markdown", "plain_text"] = Field(
        default="markdown",
        description=(
            "How to turn content into notebook blocks. Markdown supports headings, lists, code, insight tags, "
            "and query node tags."
        ),
    )
    nodes: list[ProseMirrorNode] | None = Field(
        default=None,
        description="Advanced escape hatch: one or more raw ProseMirror JSON nodes to insert.",
    )

    @model_validator(mode="after")
    def validate_content_or_nodes(self) -> "InsertContentArgs":
        if self.content is not None and self.nodes is not None:
            raise ValueError("Provide either content or nodes, not both.")
        if self.content is None and self.nodes is None:
            raise ValueError("Provide content or nodes.")
        if self.nodes is not None and len(self.nodes) == 0:
            raise ValueError("Provide at least one node.")
        if self.content is not None and not self.content.strip():
            raise ValueError("Notebook edit content must include non-empty text.")
        return self


class AppendEdit(InsertContentArgs):
    type: Literal["append"] = "append"


class InsertAfterHeadingEdit(InsertContentArgs):
    type: Literal["insert_after_heading"] = "insert_after_heading"
    heading: str = Field(description="Exact plain-text heading to insert after.")
    occurrence: int = Field(default=1, ge=1, description="Which matching heading to use.")


class InsertAfterEdit(InsertContentArgs):
    type: Literal["insert_after"] = "insert_after"
    anchor: str = Field(description="Exact text anchor. Inserts after the top-level block containing it.")
    occurrence: int = Field(default=1, ge=1, description="Which matching anchor to use.")


class InsertBeforeEdit(InsertContentArgs):
    type: Literal["insert_before"] = "insert_before"
    anchor: str = Field(description="Exact text anchor. Inserts before the top-level block containing it.")
    occurrence: int = Field(default=1, ge=1, description="Which matching anchor to use.")


class InsertBetweenEdit(InsertContentArgs):
    type: Literal["insert_between"] = "insert_between"
    after: str = Field(description="Exact text anchor in the block before the insertion point.")
    before: str = Field(description="Exact text anchor in a later block before which content is inserted.")
    after_occurrence: int = Field(default=1, ge=1, description="Which matching after anchor to use.")
    before_occurrence: int = Field(default=1, ge=1, description="Which matching before anchor to use.")


class ReplaceBlockEdit(InsertContentArgs):
    type: Literal["replace_block"] = "replace_block"
    anchor: str = Field(description="Exact text anchor inside the top-level block to replace.")
    occurrence: int = Field(default=1, ge=1, description="Which matching anchor to replace.")


class ReplaceTextEdit(BaseModel):
    type: Literal["replace_text"] = "replace_text"
    find: str = Field(
        description="Exact text to find. This can match normal notebook text and SQL inside query, HogQL, or DuckDB nodes."
    )
    replace: str = Field(description="Replacement text. Use an empty string to delete the matching text.")
    all_occurrences: bool = Field(default=False, description="Replace every exact match instead of only the first.")
    anchor: str | None = Field(
        default=None,
        description=(
            "Optional exact text anchor for a top-level block or heading. When set, only that block is searched; "
            "if the anchor is a heading, the following section is searched until the next same-or-higher-level heading."
        ),
    )
    occurrence: int = Field(
        default=1, ge=1, description="Which matching anchor block to use when anchor appears more than once."
    )


NotebookEdit = Annotated[
    AppendEdit
    | InsertAfterHeadingEdit
    | InsertAfterEdit
    | InsertBeforeEdit
    | InsertBetweenEdit
    | ReplaceBlockEdit
    | ReplaceTextEdit,
    Field(discriminator="type"),
]


class EditNotebookToolArgs(BaseModel):
    short_id: str | None = Field(
        default=None,
        description="Short ID of the notebook to edit. Omit only when exactly one notebook is in UI context.",
    )
    edits: list[NotebookEdit] = Field(description="Ordered notebook edits to apply.", min_length=1)
    title: str | None = Field(default=None, description="Optional notebook title update to save with the edit.")
    max_retries: int = Field(default=3, ge=0, le=5, description="How many times to retry after collab conflicts.")


@dataclass
class TextMatch:
    from_pos: int
    to_pos: int
    node: ProseMirrorNode
    parent: ProseMirrorNode | ProseMirrorDoc | None
    child_index: int | None
    start_index: int


class EditPlan(BaseModel):
    content: ProseMirrorDoc
    steps: list[ReplaceStep]
    text_content: str


def clone_json[T](value: T) -> T:
    return copy.deepcopy(value)


def normalize_document(content: Any) -> ProseMirrorDoc:
    if not isinstance(content, dict):
        return {"type": "doc", "content": []}

    cloned = clone_json(content)
    raw_content = cloned.get("content")
    return {
        **cloned,
        "type": "doc",
        "content": [node for node in raw_content if isinstance(node, dict)] if isinstance(raw_content, list) else [],
    }


def node_size(node: ProseMirrorNode) -> int:
    if node.get("type") == "text":
        text = node.get("text")
        return utf16_length(text) if isinstance(text, str) else 0

    content = node.get("content")
    if not isinstance(content, list):
        node_type = node.get("type")
        return 1 if isinstance(node_type, str) and (node_type.startswith("ph-") or node_type in LEAF_NODE_TYPES) else 2

    return 2 + sum(node_size(cast(ProseMirrorNode, child)) for child in content if isinstance(child, dict))


def document_content_size(doc: ProseMirrorDoc) -> int:
    return sum(node_size(child) for child in doc.get("content", []) if isinstance(child, dict))


def replace_step(from_pos: int, to_pos: int, content: list[ProseMirrorNode] | None = None) -> ReplaceStep:
    step: ReplaceStep = {"stepType": "replace", "from": from_pos, "to": to_pos}
    if content:
        step["slice"] = {"content": clone_json(content)}
    return step


def text_content(node: ProseMirrorNode | ProseMirrorDoc) -> str:
    if node.get("type") == "text":
        text = node.get("text")
        return text if isinstance(text, str) else ""

    node_type = node.get("type")
    if isinstance(node_type, str) and node_type.startswith("ph-"):
        return tiptap_doc_to_text({"type": "doc", "content": [node]})

    content = node.get("content")
    if not isinstance(content, list):
        return ""

    child_text = [text_content(child) for child in content if isinstance(child, dict)]
    child_text = [text for text in child_text if text]
    if node.get("type") in {"bulletList", "orderedList", "listItem"}:
        return "\n".join(child_text)
    return "".join(child_text)


def document_text_content(doc: ProseMirrorDoc) -> str:
    return "\n".join(
        text for text in [text_content(child) for child in doc.get("content", []) if isinstance(child, dict)] if text
    )


def top_level_position_before(doc: ProseMirrorDoc, index: int) -> int:
    position = 0
    for child in doc.get("content", [])[:index]:
        if isinstance(child, dict):
            position += node_size(child)
    return position


def top_level_position_after(doc: ProseMirrorDoc, index: int) -> int:
    position = 0
    for child in doc.get("content", [])[: index + 1]:
        if isinstance(child, dict):
            position += node_size(child)
    return position


def find_top_level_anchor_index(doc: ProseMirrorDoc, anchor: str, occurrence: int, start_index: int = 0) -> int | None:
    matches = 0
    for index, node in enumerate(doc.get("content", [])[start_index:], start=start_index):
        if not isinstance(node, dict) or anchor not in text_content(node):
            continue
        matches += 1
        if matches == occurrence:
            return index
    return None


def resolve_insert_nodes(
    edit: InsertContentArgs, viz_lookup: dict[str, dict[str, Any]], allow_executable_analysis_blocks: bool = False
) -> list[ProseMirrorNode]:
    if edit.nodes is not None:
        return clone_json(edit.nodes)

    assert edit.content is not None
    if edit.content_format == "plain_text":
        return [
            {"type": "paragraph", "content": [{"type": "text", "text": line.strip()}]}
            for line in edit.content.replace("\r\n", "\n").split("\n")
            if line.strip()
        ]

    blocks = parse_notebook_content_for_storage(edit.content)

    def resolve_visualization(artifact_id: str) -> dict[str, Any] | None:
        return viz_lookup.get(artifact_id)

    return blocks_to_tiptap_doc(
        blocks,
        resolve_visualization=resolve_visualization,
        allow_executable_analysis_blocks=allow_executable_analysis_blocks,
    ).get("content", [])


def apply_append_edit(doc: ProseMirrorDoc, nodes: list[ProseMirrorNode]) -> ReplaceStep:
    position = document_content_size(doc)
    inserted_nodes = clone_json(nodes)
    doc["content"].extend(inserted_nodes)
    return replace_step(position, position, inserted_nodes)


def apply_insert_after_heading_edit(
    doc: ProseMirrorDoc, heading: str, occurrence: int, nodes: list[ProseMirrorNode]
) -> ReplaceStep:
    matches = 0
    for index, node in enumerate(doc.get("content", [])):
        if not isinstance(node, dict) or node.get("type") != "heading" or text_content(node).strip() != heading.strip():
            continue
        matches += 1
        if matches != occurrence:
            continue

        position = top_level_position_after(doc, index)
        inserted_nodes = clone_json(nodes)
        doc["content"][index + 1 : index + 1] = inserted_nodes
        return replace_step(position, position, inserted_nodes)

    raise MaxToolRetryableError(f'Could not find heading "{heading}" in the notebook.')


def apply_insert_after_edit(
    doc: ProseMirrorDoc, anchor: str, occurrence: int, nodes: list[ProseMirrorNode]
) -> ReplaceStep:
    index = find_top_level_anchor_index(doc, anchor, occurrence)
    if index is None:
        raise MaxToolRetryableError(f'Could not find text "{anchor}" in the notebook.')

    position = top_level_position_after(doc, index)
    inserted_nodes = clone_json(nodes)
    doc["content"][index + 1 : index + 1] = inserted_nodes
    return replace_step(position, position, inserted_nodes)


def apply_insert_before_edit(
    doc: ProseMirrorDoc, anchor: str, occurrence: int, nodes: list[ProseMirrorNode]
) -> ReplaceStep:
    index = find_top_level_anchor_index(doc, anchor, occurrence)
    if index is None:
        raise MaxToolRetryableError(f'Could not find text "{anchor}" in the notebook.')

    position = top_level_position_before(doc, index)
    inserted_nodes = clone_json(nodes)
    doc["content"][index:index] = inserted_nodes
    return replace_step(position, position, inserted_nodes)


def apply_insert_between_edit(
    doc: ProseMirrorDoc,
    after: str,
    before: str,
    after_occurrence: int,
    before_occurrence: int,
    nodes: list[ProseMirrorNode],
) -> ReplaceStep:
    after_index = find_top_level_anchor_index(doc, after, after_occurrence)
    if after_index is None:
        raise MaxToolRetryableError(f'Could not find text "{after}" in the notebook.')

    before_index = find_top_level_anchor_index(doc, before, before_occurrence, after_index + 1)
    if before_index is None:
        raise MaxToolRetryableError(f'Could not find text "{before}" after "{after}" in the notebook.')

    position = top_level_position_before(doc, before_index)
    inserted_nodes = clone_json(nodes)
    doc["content"][before_index:before_index] = inserted_nodes
    return replace_step(position, position, inserted_nodes)


def apply_replace_block_edit(
    doc: ProseMirrorDoc, anchor: str, occurrence: int, nodes: list[ProseMirrorNode]
) -> ReplaceStep:
    index = find_top_level_anchor_index(doc, anchor, occurrence)
    if index is None:
        raise MaxToolRetryableError(f'Could not find text "{anchor}" in the notebook.')

    from_pos = top_level_position_before(doc, index)
    to_pos = top_level_position_after(doc, index)
    inserted_nodes = clone_json(nodes)
    doc["content"][index : index + 1] = inserted_nodes
    return replace_step(from_pos, to_pos, inserted_nodes)


def find_text_match(
    node: ProseMirrorNode | ProseMirrorDoc,
    find: str,
    position: int,
    parent: ProseMirrorNode | ProseMirrorDoc | None = None,
    child_index: int | None = None,
    start_position: int = 0,
) -> TextMatch | None:
    if node.get("type") == "text":
        text = node.get("text")
        if not isinstance(text, str):
            return None
        local_start_index = 0
        if start_position > position:
            local_start_index = code_point_index_for_utf16_offset(text, start_position - position)
        start_index = text.find(find, local_start_index)
        if start_index == -1:
            return None
        start_offset = utf16_length(text[:start_index])
        return TextMatch(
            from_pos=position + start_offset,
            to_pos=position + start_offset + utf16_length(find),
            node=node,
            parent=parent,
            child_index=child_index,
            start_index=start_index,
        )

    content = node.get("content")
    if not isinstance(content, list):
        return None

    child_position = position if node.get("type") == "doc" else position + 1
    for index, child in enumerate(content):
        if not isinstance(child, dict):
            continue
        match = find_text_match(child, find, child_position, node, index, start_position)
        if match:
            return match
        child_position += node_size(child)
    return None


def replacement_text_nodes(match: TextMatch, replacement: str) -> list[ProseMirrorNode]:
    if not replacement:
        return []

    node: ProseMirrorNode = {"type": "text", "text": replacement}
    marks = match.node.get("marks")
    if isinstance(marks, list):
        node["marks"] = clone_json(marks)
    return [node]


def replace_in_string(value: str, find: str, replacement: str, all_occurrences: bool) -> tuple[str, int]:
    if find not in value:
        return value, 0
    if not all_occurrences:
        return value.replace(find, replacement, 1), 1
    return value.replace(find, replacement), value.count(find)


def replace_strings_in_value(value: Any, find: str, replacement: str, all_occurrences: bool) -> tuple[Any, int]:
    if isinstance(value, str):
        return replace_in_string(value, find, replacement, all_occurrences)

    if isinstance(value, list):
        count = 0
        next_list_value: list[Any] = []
        for item in value:
            if not all_occurrences and count > 0:
                next_list_value.append(item)
                continue
            replacement_value, replacement_count = replace_strings_in_value(item, find, replacement, all_occurrences)
            count += replacement_count
            next_list_value.append(replacement_value)
        return next_list_value, count

    if isinstance(value, dict):
        count = 0
        next_dict_value: dict[str, Any] = {}
        for key, item in value.items():
            if not all_occurrences and count > 0:
                next_dict_value[key] = item
                continue
            replacement_value, replacement_count = replace_strings_in_value(item, find, replacement, all_occurrences)
            count += replacement_count
            next_dict_value[key] = replacement_value
        return next_dict_value, count

    return value, 0


def replace_strings_in_node_attrs(
    node: ProseMirrorNode, find: str, replacement: str, all_occurrences: bool
) -> tuple[ProseMirrorNode, int]:
    attrs = node.get("attrs")
    if not isinstance(attrs, dict):
        return node, 0

    replacement_attrs, replacement_count = replace_strings_in_value(attrs, find, replacement, all_occurrences)
    if replacement_count == 0:
        return node, 0

    return {**node, "attrs": replacement_attrs}, replacement_count


def apply_attribute_replacement_in_block(
    doc: ProseMirrorDoc, index: int, find: str, replacement: str, all_occurrences: bool
) -> list[ReplaceStep]:
    try:
        node = doc["content"][index]
    except (KeyError, IndexError):
        return []
    if not isinstance(node, dict):
        return []

    replacement_node, replacement_count = replace_strings_in_node_attrs(node, find, replacement, all_occurrences)
    if replacement_count == 0:
        return []

    from_pos = top_level_position_before(doc, index)
    to_pos = top_level_position_after(doc, index)
    inserted_node = clone_json(replacement_node)
    doc["content"][index] = inserted_node
    return [replace_step(from_pos, to_pos, [inserted_node])]


def find_attribute_replacement_block_index(
    doc: ProseMirrorDoc, find: str, start_index: int = 0, end_index: int | None = None
) -> int | None:
    content = doc.get("content", [])
    if not isinstance(content, list):
        return None
    stop_index = len(content) if end_index is None else min(end_index, len(content))
    for index in range(start_index, stop_index):
        node = content[index]
        if not isinstance(node, dict) or find not in text_content(node):
            continue
        _, replacement_count = replace_strings_in_node_attrs(node, find, find, False)
        if replacement_count > 0:
            return index
    return None


def heading_level(node: ProseMirrorNode) -> int | None:
    attrs = node.get("attrs")
    level = attrs.get("level") if isinstance(attrs, dict) else None
    return level if node.get("type") == "heading" and isinstance(level, int) else None


def find_section_end_index(doc: ProseMirrorDoc, heading_index: int) -> int:
    content = doc.get("content", [])
    if not isinstance(content, list) or heading_index >= len(content):
        return heading_index + 1

    heading = content[heading_index]
    if not isinstance(heading, dict):
        return heading_index + 1

    level = heading_level(heading)
    if level is None:
        return heading_index + 1

    for index in range(heading_index + 1, len(content)):
        node = content[index]
        if not isinstance(node, dict):
            continue
        next_level = heading_level(node)
        if next_level is not None and next_level <= level:
            return index
    return len(content)


def block_range_for_anchor(doc: ProseMirrorDoc, anchor_index: int) -> tuple[int, int]:
    content = doc.get("content", [])
    if not isinstance(content, list) or anchor_index >= len(content):
        return anchor_index, anchor_index + 1

    anchor_node = content[anchor_index]
    if not isinstance(anchor_node, dict) or anchor_node.get("type") != "heading":
        return anchor_index, anchor_index + 1

    return anchor_index + 1, find_section_end_index(doc, anchor_index)


def apply_text_match_replacement(match: TextMatch, find: str, replacement: str) -> ReplaceStep | None:
    text = match.node.get("text")
    if not isinstance(text, str):
        return None

    match.node["text"] = f"{text[: match.start_index]}{replacement}{text[match.start_index + len(find) :]}"
    if (
        not match.node["text"]
        and match.parent
        and match.child_index is not None
        and isinstance(match.parent.get("content"), list)
    ):
        match.parent["content"].pop(match.child_index)

    return replace_step(match.from_pos, match.to_pos, replacement_text_nodes(match, replacement))


def apply_text_replacement(
    doc: ProseMirrorDoc, find: str, replacement: str, start_position: int = 0
) -> tuple[ReplaceStep, int] | None:
    match = find_text_match(doc, find, 0, start_position=start_position)
    if not match:
        return None
    next_position = match.from_pos + utf16_length(replacement)
    step = apply_text_match_replacement(match, find, replacement)
    if not step:
        return None
    return step, next_position


def apply_text_replacement_in_block(
    doc: ProseMirrorDoc, index: int, find: str, replacement: str, start_position: int = 0
) -> tuple[ReplaceStep, int] | None:
    try:
        node = doc["content"][index]
    except (KeyError, IndexError):
        return None
    if not isinstance(node, dict):
        return None

    match = find_text_match(node, find, top_level_position_before(doc, index), start_position=start_position)
    if not match:
        return None
    next_position = match.from_pos + utf16_length(replacement)
    step = apply_text_match_replacement(match, find, replacement)
    if not step:
        return None
    return step, next_position


def assert_replacement_limit(find: str, replacement_count: int) -> None:
    if replacement_count > MAX_TEXT_REPLACEMENTS:
        raise MaxToolRetryableError(
            f'Stopped after {MAX_TEXT_REPLACEMENTS} replacements for "{find}". Narrow the edit target.'
        )


def apply_replacements_in_block_range(
    doc: ProseMirrorDoc,
    start_index: int,
    end_index: int,
    find: str,
    replacement: str,
    all_occurrences: bool,
) -> list[ReplaceStep]:
    steps: list[ReplaceStep] = []
    replacements = 0

    for index in range(start_index, end_index):
        attribute_steps = apply_attribute_replacement_in_block(doc, index, find, replacement, all_occurrences)
        if attribute_steps:
            steps.extend(attribute_steps)
            replacements += len(attribute_steps)
            if not all_occurrences:
                return steps
            assert_replacement_limit(find, replacements)
            continue

        search_position = top_level_position_before(doc, index)
        while True:
            text_replacement = apply_text_replacement_in_block(doc, index, find, replacement, search_position)
            if not text_replacement:
                break
            step, search_position = text_replacement
            steps.append(step)
            replacements += 1
            if not all_occurrences:
                return steps
            assert_replacement_limit(find, replacements)

    return steps


def apply_replace_text_edit(
    doc: ProseMirrorDoc,
    find: str,
    replacement: str,
    all_occurrences: bool,
    anchor: str | None = None,
    occurrence: int = 1,
) -> list[ReplaceStep]:
    if anchor:
        anchor_index = find_top_level_anchor_index(doc, anchor, occurrence)
        if anchor_index is None:
            raise MaxToolRetryableError(f'Could not find text "{anchor}" in the notebook.')

        start_index, end_index = block_range_for_anchor(doc, anchor_index)
        anchored_steps = apply_replacements_in_block_range(
            doc, start_index, end_index, find, replacement, all_occurrences
        )
        if anchored_steps:
            return anchored_steps

        raise MaxToolRetryableError(
            f'Could not find text "{find}" inside notebook block or section anchored by "{anchor}".'
        )

    steps: list[ReplaceStep] = []
    replacements = 0

    if all_occurrences:
        content = doc.get("content", [])
        if isinstance(content, list):
            for index in range(len(content)):
                attribute_steps = apply_attribute_replacement_in_block(doc, index, find, replacement, True)
                steps.extend(attribute_steps)
                replacements += len(attribute_steps)
                assert_replacement_limit(find, replacements)

        search_position = 0
        while True:
            text_replacement = apply_text_replacement(doc, find, replacement, search_position)
            if not text_replacement:
                break
            step, search_position = text_replacement
            steps.append(step)
            replacements += 1
            assert_replacement_limit(find, replacements)

        if not steps:
            raise MaxToolRetryableError(f'Could not find text "{find}" in the notebook.')
        return steps

    while True:
        attribute_index = find_attribute_replacement_block_index(doc, find)
        if attribute_index is not None:
            attribute_steps = apply_attribute_replacement_in_block(doc, attribute_index, find, replacement, False)
            steps.extend(attribute_steps)
            replacements += len(attribute_steps)
        else:
            text_replacement = apply_text_replacement(doc, find, replacement)
            if not text_replacement:
                break
            step, _ = text_replacement
            steps.append(step)
            replacements += 1

        break

    if not steps:
        raise MaxToolRetryableError(f'Could not find text "{find}" in the notebook.')
    return steps


def apply_notebook_edit(
    doc: ProseMirrorDoc,
    edit: NotebookEdit,
    viz_lookup: dict[str, dict[str, Any]],
    allow_executable_analysis_blocks: bool = False,
) -> list[ReplaceStep]:
    if isinstance(edit, AppendEdit):
        return [apply_append_edit(doc, resolve_insert_nodes(edit, viz_lookup, allow_executable_analysis_blocks))]
    if isinstance(edit, InsertAfterHeadingEdit):
        return [
            apply_insert_after_heading_edit(
                doc,
                edit.heading,
                edit.occurrence,
                resolve_insert_nodes(edit, viz_lookup, allow_executable_analysis_blocks),
            )
        ]
    if isinstance(edit, InsertAfterEdit):
        return [
            apply_insert_after_edit(
                doc,
                edit.anchor,
                edit.occurrence,
                resolve_insert_nodes(edit, viz_lookup, allow_executable_analysis_blocks),
            )
        ]
    if isinstance(edit, InsertBeforeEdit):
        return [
            apply_insert_before_edit(
                doc,
                edit.anchor,
                edit.occurrence,
                resolve_insert_nodes(edit, viz_lookup, allow_executable_analysis_blocks),
            )
        ]
    if isinstance(edit, InsertBetweenEdit):
        return [
            apply_insert_between_edit(
                doc,
                edit.after,
                edit.before,
                edit.after_occurrence,
                edit.before_occurrence,
                resolve_insert_nodes(edit, viz_lookup, allow_executable_analysis_blocks),
            )
        ]
    if isinstance(edit, ReplaceBlockEdit):
        return [
            apply_replace_block_edit(
                doc,
                edit.anchor,
                edit.occurrence,
                resolve_insert_nodes(edit, viz_lookup, allow_executable_analysis_blocks),
            )
        ]
    if isinstance(edit, ReplaceTextEdit):
        return apply_replace_text_edit(doc, edit.find, edit.replace, edit.all_occurrences, edit.anchor, edit.occurrence)

    raise MaxToolRetryableError("Unsupported notebook edit type.")


def referenced_visualization_ids(edits: list[NotebookEdit]) -> list[str]:
    ref_ids: list[str] = []
    for edit in edits:
        if not isinstance(edit, InsertContentArgs) or edit.content is None:
            continue
        blocks = parse_notebook_content_for_storage(edit.content)
        ref_ids.extend(block.artifact_id for block in blocks if isinstance(block, VisualizationRefBlock))
    return ref_ids


async def build_visualization_lookup(team_id: int, ref_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ref_ids:
        return {}

    viz_lookup: dict[str, dict[str, Any]] = {}
    async for viz_artifact in AgentArtifact.objects.filter(short_id__in=ref_ids, team_id=team_id):
        data = viz_artifact.data
        if data.get("content_type") != "visualization":
            continue
        query = data.get("query")
        if not isinstance(query, dict):
            continue
        kind = query.get("kind", "")
        if kind == "DataVisualizationNode":
            notebook_query = query
        elif kind == "HogQLQuery" or "HogQL" in kind:
            notebook_query = {"kind": "DataVisualizationNode", "source": query}
        else:
            notebook_query = {"kind": "InsightVizNode", "source": query}
        viz_lookup[viz_artifact.short_id] = {"query": notebook_query, "name": data.get("name")}
    return viz_lookup


def edits_use_executable_analysis_blocks(edits: list[NotebookEdit]) -> bool:
    for edit in edits:
        if not isinstance(edit, InsertContentArgs):
            continue
        if content_uses_executable_analysis_blocks(edit.content):
            return True
        if nodes_use_executable_analysis_blocks(edit.nodes):
            return True
    return False


def collect_executable_analysis_nodes(value: Any, nodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if nodes is None:
        nodes = []

    if isinstance(value, list):
        for item in value:
            collect_executable_analysis_nodes(item, nodes)
        return nodes

    if not isinstance(value, dict):
        return nodes

    if value.get("type") in EXECUTABLE_ANALYSIS_NODE_TYPES:
        nodes.append(value)
        return nodes

    for item in value.values():
        collect_executable_analysis_nodes(item, nodes)
    return nodes


def executable_analysis_nodes_changed(before: ProseMirrorDoc, after: ProseMirrorDoc) -> bool:
    return collect_executable_analysis_nodes(before) != collect_executable_analysis_nodes(after)


def build_edit_plan(
    content: Any,
    edits: list[NotebookEdit],
    viz_lookup: dict[str, dict[str, Any]],
    allow_executable_analysis_blocks: bool = False,
) -> EditPlan:
    doc = normalize_document(content)
    steps: list[ReplaceStep] = []
    for edit in edits:
        steps.extend(apply_notebook_edit(doc, edit, viz_lookup, allow_executable_analysis_blocks))

    return EditPlan(content=doc, steps=steps, text_content=document_text_content(doc))


def markdown_to_plain_text(markdown: str) -> str:
    doc = {"type": "doc", "content": markdown_to_tiptap_nodes(markdown)}
    return document_text_content(doc)


def rewrite_first_append_for_notebook_request_location(
    edits: list[NotebookEdit], request_location: MaxNotebookRequestLocationContext | None
) -> list[NotebookEdit]:
    if not request_location:
        return edits
    if not any(isinstance(edit, AppendEdit) for edit in edits):
        return edits

    placeholder_anchor = ai_placeholder_anchor_from_request_location(request_location)
    if placeholder_anchor and any(
        isinstance(edit, ReplaceBlockEdit) and edit.anchor.strip() == placeholder_anchor for edit in edits
    ):
        return edits

    replaced = False
    rewritten_edits: list[NotebookEdit] = []
    for edit in edits:
        if not replaced and isinstance(edit, AppendEdit):
            rewritten_edit = request_location_append_replacement(edit, request_location, placeholder_anchor)
            rewritten_edits.append(rewritten_edit)
            replaced = True
            continue

        rewritten_edits.append(edit)

    return rewritten_edits


def ai_placeholder_anchor_from_request_location(request_location: MaxNotebookRequestLocationContext) -> str | None:
    current_block_text = request_location.current_block_text
    if not current_block_text:
        return None

    anchor = current_block_text.strip()
    if anchor.startswith(AI_PLACEHOLDER_PREFIX) and AI_PLACEHOLDER_SUFFIX in anchor:
        return anchor
    return None


def request_location_append_replacement(
    edit: AppendEdit, request_location: MaxNotebookRequestLocationContext, placeholder_anchor: str | None
) -> NotebookEdit:
    if placeholder_anchor:
        return ReplaceBlockEdit(
            anchor=placeholder_anchor,
            content=edit.content,
            content_format=edit.content_format,
            nodes=edit.nodes,
        )

    previous_block_text = request_location.previous_block_text.strip() if request_location.previous_block_text else ""
    next_block_text = request_location.next_block_text.strip() if request_location.next_block_text else ""
    if previous_block_text and next_block_text:
        return InsertBetweenEdit(
            after=previous_block_text,
            before=next_block_text,
            content=edit.content,
            content_format=edit.content_format,
            nodes=edit.nodes,
        )
    if previous_block_text:
        return InsertAfterEdit(
            anchor=previous_block_text,
            content=edit.content,
            content_format=edit.content_format,
            nodes=edit.nodes,
        )
    if next_block_text:
        return InsertBeforeEdit(
            anchor=next_block_text,
            content=edit.content,
            content_format=edit.content_format,
            nodes=edit.nodes,
        )
    return edit


class EditNotebookTool(MaxTool):
    name: Literal[AssistantTool.EDIT_NOTEBOOK] = AssistantTool.EDIT_NOTEBOOK
    args_schema: type[BaseModel] = EditNotebookToolArgs
    description: str = EDIT_NOTEBOOK_PROMPT

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("notebook", "editor")]

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        description = build_edit_notebook_prompt(
            allow_executable_analysis_blocks=has_notebook_python_feature_flag(team, user)
        )
        return cls(
            team=team,
            user=user,
            node_path=node_path,
            state=state,
            config=config,
            context_manager=context_manager,
            description=description,
        )

    def _current_context_notebook(self) -> MaxNotebookContext | None:
        ui_context = self._context_manager.get_ui_context(self._state)
        if not isinstance(ui_context, MaxUIContext) or not ui_context.notebooks or len(ui_context.notebooks) != 1:
            return None
        return ui_context.notebooks[0]

    def _current_context_notebook_id(self) -> str | None:
        notebook = self._current_context_notebook()
        return notebook.id if notebook else None

    def _current_context_notebook_request_location(self) -> MaxNotebookRequestLocationContext | None:
        notebook = self._current_context_notebook()
        if not notebook or not notebook.request_location:
            return None
        return notebook.request_location

    async def _get_notebook(self, short_id: str) -> Notebook:
        try:
            notebook = await Notebook.objects.aget(team=self._team, short_id=short_id, deleted=False)
        except Notebook.DoesNotExist:
            raise MaxToolRetryableError(f"Notebook with short_id={short_id} not found.")

        await self.check_object_access(notebook, "editor", resource="notebook", action="edit")
        return notebook

    async def _save_plan(self, notebook: Notebook, plan: EditPlan, title: str | None) -> Notebook | None:
        result = await sync_to_async(submit_steps, thread_sensitive=False)(
            team_id=notebook.team_id,
            notebook_id=str(notebook.short_id),
            client_id=f"max-{uuid.uuid4()}",
            steps_json=plan.steps,
            last_seen_version=notebook.version,
            last_saved_version=notebook.version,
            user_id=self._user.pk,
            user_name=self._user.get_full_name() or "PostHog AI",
        )

        if result.status != "accepted":
            return None

        await Notebook.objects.filter(pk=notebook.pk).aupdate(
            content=annotate_python_nodes(plan.content),
            text_content=plan.text_content,
            title=title if title is not None else notebook.title,
            version=result.version,
            last_modified_at=now(),
            last_modified_by=self._user,
        )
        return await Notebook.objects.aget(pk=notebook.pk)

    async def _update_title_only(self, notebook: Notebook, title: str) -> Notebook:
        await Notebook.objects.filter(pk=notebook.pk).aupdate(
            title=title,
            last_modified_at=now(),
            last_modified_by=self._user,
        )
        return await Notebook.objects.aget(pk=notebook.pk)

    async def _arun_impl(
        self,
        edits: list[NotebookEdit],
        short_id: str | None = None,
        title: str | None = None,
        max_retries: int = 3,
    ) -> tuple[str, Any]:
        target_short_id = short_id or self._current_context_notebook_id()
        if not target_short_id:
            return (
                "Error: No notebook short_id was provided, and there is not exactly one notebook in the current context.",
                None,
            )

        request_location = self._current_context_notebook_request_location()
        placeholder_anchor = (
            ai_placeholder_anchor_from_request_location(request_location) if request_location is not None else None
        )
        edits_to_apply = rewrite_first_append_for_notebook_request_location(edits, request_location)

        viz_lookup = await build_visualization_lookup(self._team.pk, referenced_visualization_ids(edits_to_apply))
        allow_executable_analysis_blocks = has_notebook_python_feature_flag(self._team, self._user)
        if not allow_executable_analysis_blocks and edits_use_executable_analysis_blocks(edits_to_apply):
            return EXECUTABLE_ANALYSIS_BLOCK_ERROR, None

        for _attempt in range(max_retries + 1):
            notebook = await self._get_notebook(target_short_id)
            try:
                original_content = normalize_document(notebook.content)
                plan = build_edit_plan(
                    notebook.content,
                    edits_to_apply,
                    viz_lookup,
                    allow_executable_analysis_blocks=allow_executable_analysis_blocks,
                )
                if not allow_executable_analysis_blocks and executable_analysis_nodes_changed(
                    original_content, plan.content
                ):
                    return EXECUTABLE_ANALYSIS_BLOCK_ERROR, None
            except MaxToolRetryableError as error:
                if placeholder_anchor and placeholder_anchor in str(error) and _attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                raise

            if not plan.steps:
                if title is None:
                    return "Error: No notebook edits were generated.", None
                updated = await self._update_title_only(notebook, title)
                return f"Updated notebook {updated.short_id}.", {"short_id": updated.short_id}

            saved_notebook = await self._save_plan(notebook, plan, title)
            if saved_notebook is None:
                continue

            return (
                f"Updated notebook {saved_notebook.short_id} with {len(edits_to_apply)} edit{'s' if len(edits_to_apply) != 1 else ''}.",
                {"short_id": saved_notebook.short_id, "applied_edits": len(edits_to_apply)},
            )

        raise MaxToolRetryableError(
            f"Could not apply notebook edit after {max_retries + 1} attempts because the notebook kept changing."
        )
