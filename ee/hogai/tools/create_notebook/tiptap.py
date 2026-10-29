import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from posthog.schema import MarkdownBlock, SessionReplayBlock

from posthog.comment.tiptap import markdown_to_tiptap_nodes

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


def _paragraph(content: list[dict]) -> dict:
    if not content:
        return {"type": "paragraph"}
    return {"type": "paragraph", "content": content}


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

    if node_type == "ph-recording":
        session_id = attrs.get("id", "unknown")
        return f'<session_replay id="{session_id}" />'

    if node_type == "ph-markdown-notebook":
        markdown = attrs.get("markdown")
        return markdown if isinstance(markdown, str) else ""

    # Fallback: try to extract text from children
    children = node.get("content", [])
    if children:
        return _tiptap_inline_to_text(children)
    return ""


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
