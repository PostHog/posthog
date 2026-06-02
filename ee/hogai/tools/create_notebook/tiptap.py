import re
import html
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from posthog.schema import MarkdownBlock, SessionReplayBlock

from ee.hogai.artifacts.types import VisualizationRefBlock

ANALYSIS_BLOCK_PATTERN = re.compile(
    r"(?ims)^[ \t]*<(python|hogql|ducksql|duckdb|query)\b([^>]*)>\n?(.*?)\n?</\1>[ \t]*$"
)
EXECUTABLE_ANALYSIS_BLOCK_PATTERN = re.compile(
    r"(?ims)^[ \t]*<(python|hogql|ducksql|duckdb)\b([^>]*)>\n?(.*?)\n?</\1>[ \t]*$"
)
ATTRIBUTE_PATTERN = re.compile(r"""([A-Za-z_][\w:-]*)\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+)""")
EXECUTABLE_ANALYSIS_NODE_TYPES = {"ph-python", "ph-hogql-sql", "ph-duck-sql"}


def blocks_to_tiptap_doc(
    blocks: Sequence[BaseModel],
    title: str | None = None,
    resolve_visualization: Any | None = None,
    allow_executable_analysis_blocks: bool = False,
) -> dict:
    """
    Convert stored notebook blocks to a tiptap document structure.

    Args:
        blocks: List of StoredBlock from the notebook artifact.
        title: Optional title for the notebook (added as heading).
        resolve_visualization: Optional callable(artifact_id) -> dict|None
            that returns query data for a VisualizationRefBlock.
            Should return {"query": ..., "name": ...} or None.

    Returns:
        A tiptap document dict: {"type": "doc", "content": [...]}
    """
    content: list[dict] = []

    if title:
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": title}],
            }
        )

    for block in blocks:
        content.extend(
            _block_to_tiptap_nodes(
                block,
                resolve_visualization,
                allow_executable_analysis_blocks=allow_executable_analysis_blocks,
            )
        )

    if not content:
        content.append({"type": "paragraph"})

    return {"type": "doc", "content": content}


def _block_to_tiptap_nodes(
    block: BaseModel,
    resolve_visualization: Any | None = None,
    allow_executable_analysis_blocks: bool = False,
) -> list[dict]:
    if isinstance(block, MarkdownBlock):
        return markdown_to_tiptap_nodes(
            block.content, allow_executable_analysis_blocks=allow_executable_analysis_blocks
        )
    elif isinstance(block, VisualizationRefBlock):
        return _visualization_ref_to_tiptap(block, resolve_visualization)
    elif isinstance(block, SessionReplayBlock):
        return [
            {
                "type": "ph-recording",
                "attrs": {
                    "id": block.session_id,
                    "__init": {"expanded": True},
                },
            }
        ]
    else:
        return []


def _visualization_ref_to_tiptap(
    block: VisualizationRefBlock,
    resolve_visualization: Any | None = None,
) -> list[dict]:
    if resolve_visualization is None:
        return [_paragraph([{"type": "text", "text": f"[Visualization: {block.artifact_id}]"}])]

    viz_data = resolve_visualization(block.artifact_id)
    if viz_data is None:
        return [_paragraph([{"type": "text", "text": f"[Visualization not found: {block.artifact_id}]"}])]

    query = viz_data.get("query")
    name = viz_data.get("name") or block.title

    return [
        {
            "type": "ph-query",
            "attrs": {
                "query": query,
                "title": name,
            },
        }
    ]


def markdown_to_tiptap_nodes(text: str, allow_executable_analysis_blocks: bool = False) -> list[dict]:
    """
    Convert a markdown string to a list of tiptap nodes.

    Supports:
    - Headings (# to ######)
    - Paragraphs
    - Bullet lists (- or *)
    - Ordered lists (1.)
    - Code blocks (triple backtick)
    - Analysis blocks: <query>, and optionally <python>, <hogql>, and <ducksql>
    - Inline: **bold**, *italic*, `code`, [text](url)
    """
    return _markdown_to_tiptap_nodes_with_analysis_blocks(
        text, allow_executable_analysis_blocks=allow_executable_analysis_blocks
    )


def _markdown_to_tiptap_nodes_with_analysis_blocks(
    text: str, allow_executable_analysis_blocks: bool = False
) -> list[dict]:
    if not text or not text.strip():
        return []

    nodes: list[dict] = []
    last_end = 0
    for match in ANALYSIS_BLOCK_PATTERN.finditer(text):
        nodes.extend(_markdown_to_tiptap_nodes(text[last_end : match.start()]))
        tag = match.group(1)
        if tag in {"python", "hogql", "ducksql", "duckdb"} and not allow_executable_analysis_blocks:
            nodes.extend(_markdown_to_tiptap_nodes(match.group(0)))
            last_end = match.end()
            continue

        analysis_node = _analysis_block_to_tiptap_node(tag, match.group(2), match.group(3))
        if analysis_node:
            nodes.append(analysis_node)
        last_end = match.end()
    nodes.extend(_markdown_to_tiptap_nodes(text[last_end:]))
    return nodes


def content_uses_executable_analysis_blocks(text: str | None) -> bool:
    return bool(text and EXECUTABLE_ANALYSIS_BLOCK_PATTERN.search(text))


def nodes_use_executable_analysis_blocks(nodes: list[dict] | None) -> bool:
    if not nodes:
        return False

    for node in nodes:
        if node.get("type") in EXECUTABLE_ANALYSIS_NODE_TYPES:
            return True
        content = node.get("content")
        if isinstance(content, list) and nodes_use_executable_analysis_blocks(
            [child for child in content if isinstance(child, dict)]
        ):
            return True
    return False


def _markdown_to_tiptap_nodes(text: str) -> list[dict]:
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    nodes: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Code block
        if line.strip().startswith("```"):
            code_lines: list[str] = []
            lang = line.strip()[3:].strip() or None
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            attrs = {}
            if lang:
                attrs["language"] = lang
            node: dict = {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "\n".join(code_lines)}],
            }
            if attrs:
                node["attrs"] = attrs
            nodes.append(node)
            continue

        # Heading
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            inline = _parse_inline(heading_match.group(2).strip())
            nodes.append(
                {
                    "type": "heading",
                    "attrs": {"level": level},
                    "content": inline,
                }
            )
            i += 1
            continue

        # Unordered list
        if re.match(r"^\s*[-*]\s+", line):
            items: list[dict] = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                item_text = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append(
                    {
                        "type": "listItem",
                        "content": [_paragraph(_parse_inline(item_text))],
                    }
                )
                i += 1
            nodes.append({"type": "bulletList", "content": items})
            continue

        # Ordered list
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                item_text = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                items.append(
                    {
                        "type": "listItem",
                        "content": [_paragraph(_parse_inline(item_text))],
                    }
                )
                i += 1
            nodes.append({"type": "orderedList", "content": items})
            continue

        # Empty line
        if not line.strip():
            i += 1
            continue

        # Paragraph (collect consecutive non-empty, non-special lines)
        para_lines: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_special_line(lines[i]):
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            inline = _parse_inline(" ".join(para_lines))
            nodes.append(_paragraph(inline))

    return nodes


def _parse_block_attributes(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in ATTRIBUTE_PATTERN.finditer(raw_attrs):
        raw_value = match.group(2)
        value = raw_value[1:-1] if raw_value[:1] in {'"', "'"} and raw_value[-1:] == raw_value[:1] else raw_value
        attrs[match.group(1).replace("-", "_").lower()] = html.unescape(value)
    return attrs


def _analysis_block_to_tiptap_node(tag: str, raw_attrs: str, raw_body: str) -> dict | None:
    attrs = _parse_block_attributes(raw_attrs)
    body = html.unescape(raw_body.strip("\n"))
    title = attrs.get("title")

    if tag == "python":
        node_attrs: dict[str, Any] = {"code": body, "__init": {"showSettings": True}}
        if title:
            node_attrs["title"] = title
        return {"type": "ph-python", "attrs": node_attrs}

    if tag in {"hogql", "ducksql", "duckdb"}:
        default_variable = "hogql_df" if tag == "hogql" else "duck_df"
        node_attrs = {
            "code": body,
            "returnVariable": attrs.get("return_variable") or attrs.get("returnvariable") or default_variable,
            "__init": {"showSettings": True},
        }
        if title:
            node_attrs["title"] = title
        return {"type": "ph-hogql-sql" if tag == "hogql" else "ph-duck-sql", "attrs": node_attrs}

    if tag == "query":
        try:
            query = json.loads(body)
        except ValueError:
            return _paragraph([{"type": "text", "text": "[Invalid query JSON]"}])
        if not isinstance(query, dict):
            return _paragraph([{"type": "text", "text": "[Invalid query JSON]"}])
        return {"type": "ph-query", "attrs": {"query": query, "title": title}}

    return None


def _is_special_line(line: str) -> bool:
    if line.strip().startswith("```"):
        return True
    if re.match(r"^#{1,6}\s+", line):
        return True
    if re.match(r"^\s*[-*]\s+", line):
        return True
    if re.match(r"^\s*\d+\.\s+", line):
        return True
    return False


def _paragraph(content: list[dict]) -> dict:
    if not content:
        return {"type": "paragraph"}
    return {"type": "paragraph", "content": content}


def _parse_inline(text: str) -> list[dict]:
    """
    Parse inline markdown into tiptap text nodes with marks.

    Handles: **bold**, *italic*, `code`, [text](url)
    """
    if not text:
        return []

    nodes: list[dict] = []
    # Pattern matches: **bold**, *italic*, `code`, [text](url), or plain text
    pattern = re.compile(
        r"(\*\*(.+?)\*\*)"  # bold
        r"|(\*(.+?)\*)"  # italic
        r"|(`(.+?)`)"  # inline code
        r"|(\[([^\]]+)\]\(([^)]+)\))"  # link
    )

    pos = 0
    for match in pattern.finditer(text):
        # Add preceding plain text
        if match.start() > pos:
            plain = text[pos : match.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})

        if match.group(2) is not None:
            # Bold
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(2),
                    "marks": [{"type": "bold"}],
                }
            )
        elif match.group(4) is not None:
            # Italic
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(4),
                    "marks": [{"type": "italic"}],
                }
            )
        elif match.group(6) is not None:
            # Inline code
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(6),
                    "marks": [{"type": "code"}],
                }
            )
        elif match.group(8) is not None:
            # Link
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(8),
                    "marks": [{"type": "link", "attrs": {"href": match.group(9)}}],
                }
            )

        pos = match.end()

    # Add remaining plain text
    if pos < len(text):
        remaining = text[pos:]
        if remaining:
            nodes.append({"type": "text", "text": remaining})

    if not nodes and text:
        nodes.append({"type": "text", "text": text})

    return nodes


# ---------------------------------------------------------------------------
# Tiptap → simplified text (for the agent to read notebook content)
# ---------------------------------------------------------------------------


def tiptap_doc_to_text(doc: dict | None) -> str:
    """
    Convert a tiptap document dict to a simplified markdown-like text.

    Handles standard tiptap nodes (heading, paragraph, bulletList, orderedList,
    codeBlock) as well as PostHog-specific nodes (ph-query, ph-python, SQL nodes,
    ph-recording).
    """
    if not doc or not isinstance(doc, dict):
        return ""

    content = doc.get("content", [])
    if not content:
        return ""

    parts: list[str] = []
    for node in content:
        text = _tiptap_node_to_text(node)
        if text:
            parts.append(text)

    return "\n\n".join(parts)


def _coerce_to_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tiptap_node_to_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type", "")
    attrs = _coerce_to_dict(node.get("attrs"))

    if node_type == "heading":
        level = attrs.get("level", 1)
        inline = _tiptap_inline_to_text(node.get("content", []))
        return f"{'#' * level} {inline}"

    if node_type == "paragraph":
        return _tiptap_inline_to_text(node.get("content", []))

    if node_type == "codeBlock":
        lang = attrs.get("language", "")
        code = _tiptap_inline_to_text(node.get("content", []))
        return f"```{lang}\n{code}\n```"

    if node_type == "bulletList":
        items = []
        for item in node.get("content", []):
            item_text = _tiptap_list_item_to_text(item)
            items.append(f"- {item_text}")
        return "\n".join(items)

    if node_type == "orderedList":
        items = []
        for i, item in enumerate(node.get("content", []), 1):
            item_text = _tiptap_list_item_to_text(item)
            items.append(f"{i}. {item_text}")
        return "\n".join(items)

    if node_type == "ph-query":
        title = attrs.get("title", "Untitled")
        # `attrs.query` is sometimes persisted as a JSON-encoded string rather than a dict,
        # which used to crash the LangGraph root node when the agent surfaced a notebook.
        query = _coerce_to_dict(attrs.get("query"))
        query_kind = query.get("kind", "unknown")
        source = _coerce_to_dict(query.get("source"))
        source_kind = source.get("kind", "")
        parts = [f'<insight title="{title}" query_kind="{query_kind}"']
        if source_kind:
            parts[0] += f' source_kind="{source_kind}"'
        parts[0] += ">"
        parts.append(json.dumps(query, separators=(",", ":"), default=str))
        parts.append("</insight>")
        return "\n".join(parts)

    if node_type == "ph-python":
        return _format_code_node("python", attrs)

    if node_type == "ph-hogql-sql":
        return _format_code_node("hogql", attrs)

    if node_type == "ph-duck-sql":
        return _format_code_node("ducksql", attrs)

    if node_type == "ph-ai":
        placeholder_id = attrs.get("id")
        id_attribute = f' id="{html.escape(str(placeholder_id), quote=True)}"' if placeholder_id else ""
        return f"<AI{id_attribute}>Thinking...</AI>"

    if node_type == "ph-recording":
        session_id = attrs.get("id", "unknown")
        return f'<session_replay id="{session_id}" />'

    # Fallback: try to extract text from children
    children = node.get("content", [])
    if children:
        return _tiptap_inline_to_text(children)
    return ""


def _format_code_node(tag: str, attrs: dict) -> str:
    title = attrs.get("title")
    return_variable = attrs.get("returnVariable")
    code = attrs.get("code", "")
    attr_parts = []
    if isinstance(title, str) and title:
        attr_parts.append(f'title="{title}"')
    if isinstance(return_variable, str) and return_variable and tag in {"hogql", "ducksql"}:
        attr_parts.append(f'return_variable="{return_variable}"')
    attrs_text = f" {' '.join(attr_parts)}" if attr_parts else ""
    return f"<{tag}{attrs_text}>\n{code}\n</{tag}>"


def _tiptap_list_item_to_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    children = item.get("content", [])
    parts = []
    for child in children:
        parts.append(_tiptap_node_to_text(child))
    return " ".join(p for p in parts if p)


def _tiptap_inline_to_text(nodes: Any) -> str:
    if not isinstance(nodes, list):
        return ""
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "text":
            text = node.get("text", "")
            marks = node.get("marks", [])
            for mark in marks:
                mark_type = mark.get("type", "")
                if mark_type == "bold":
                    text = f"**{text}**"
                elif mark_type == "italic":
                    text = f"*{text}*"
                elif mark_type == "code":
                    text = f"`{text}`"
                elif mark_type == "link":
                    href = mark.get("attrs", {}).get("href", "")
                    text = f"[{text}]({href})"
            parts.append(text)
        elif node.get("type") == "hardBreak":
            parts.append("\n")
        else:
            # Recursive for nested inline content
            child_text = _tiptap_node_to_text(node)
            if child_text:
                parts.append(child_text)
    return "".join(parts)
