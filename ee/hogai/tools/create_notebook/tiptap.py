import re
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from posthog.schema import MarkdownBlock, SessionReplayBlock

from ee.hogai.artifacts.types import VisualizationRefBlock


def blocks_to_tiptap_doc(
    blocks: Sequence[BaseModel],
    title: str | None = None,
    resolve_visualization: Any | None = None,
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
        content.extend(_block_to_tiptap_nodes(block, resolve_visualization))

    if not content:
        content.append({"type": "paragraph"})

    return {"type": "doc", "content": content}


def _block_to_tiptap_nodes(
    block: BaseModel,
    resolve_visualization: Any | None = None,
) -> list[dict]:
    if isinstance(block, MarkdownBlock):
        return markdown_to_tiptap_nodes(block.content)
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


def markdown_to_tiptap_nodes(text: str) -> list[dict]:
    """
    Convert a markdown string to a list of tiptap nodes.

    Supports:
    - Headings (# to ######)
    - Paragraphs
    - Bullet lists (- or *)
    - Ordered lists (1.)
    - Code blocks (triple backtick)
    - Inline: **bold**, *italic*, `code`, [text](url)
    """
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
    codeBlock) as well as PostHog-specific nodes (ph-query, ph-recording).
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


def _tiptap_node_to_text(node: dict) -> str:
    node_type = node.get("type", "")

    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 1)
        inline = _tiptap_inline_to_text(node.get("content", []))
        return f"{'#' * level} {inline}"

    if node_type == "paragraph":
        return _tiptap_inline_to_text(node.get("content", []))

    if node_type == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
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
        attrs = node.get("attrs", {})
        title = attrs.get("title", "Untitled")
        query = attrs.get("query", {})
        query_kind = query.get("kind", "unknown")
        source = query.get("source", {})
        source_kind = source.get("kind", "") if isinstance(source, dict) else ""
        parts = [f'<insight title="{title}" query_kind="{query_kind}"']
        if source_kind:
            parts[0] += f' source_kind="{source_kind}"'
        parts[0] += ">"
        parts.append(json.dumps(query, separators=(",", ":"), default=str))
        parts.append("</insight>")
        return "\n".join(parts)

    if node_type == "ph-recording":
        attrs = node.get("attrs", {})
        session_id = attrs.get("id", "unknown")
        return f'<session_replay id="{session_id}" />'

    # Fallback: try to extract text from children
    children = node.get("content", [])
    if children:
        return _tiptap_inline_to_text(children)
    return ""


def _tiptap_list_item_to_text(item: dict) -> str:
    children = item.get("content", [])
    parts = []
    for child in children:
        parts.append(_tiptap_node_to_text(child))
    return " ".join(p for p in parts if p)


def _tiptap_inline_to_text(nodes: list[dict]) -> str:
    parts: list[str] = []
    for node in nodes:
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
