import uuid
from typing import Any

# Type aliases for TipTap editor nodes
TipTapNode = dict[str, Any]
TipTapContent = list[TipTapNode]


def create_bullet_list(items: list[str] | list[TipTapContent] | TipTapContent) -> TipTapNode:
    """Create a bullet list with list items. Items can be strings or content arrays."""
    list_items = []
    for item in items:
        if isinstance(item, str):
            list_items.append({"type": "listItem", "content": [create_paragraph_with_text(item)]})
        elif isinstance(item, list):
            # item is already a content array (could be paragraph + nested list)
            list_items.append({"type": "listItem", "content": item})
        else:
            # item is a single content node
            list_items.append({"type": "listItem", "content": [create_paragraph_with_content([item])]})

    return {"type": "bulletList", "content": list_items}


def create_heading_with_text(text: str, level: int, *, collapsed: bool = False) -> TipTapNode:
    """Create a heading node with sanitized text content."""
    heading_id = str(uuid.uuid4())
    return {
        "type": "heading",
        "attrs": {"id": heading_id, "level": level, "data-toc-id": heading_id, "collapsed": collapsed},
        "content": [{"type": "text", "text": sanitize_text_content(text)}],
    }


def create_paragraph_with_text(text: str, marks: list[dict[str, Any]] | None = None) -> TipTapNode:
    """Create a paragraph node with sanitized text content and optional marks."""
    content_node: dict[str, Any] = {"type": "text", "text": sanitize_text_content(text)}
    if marks:
        content_node["marks"] = marks
    return {
        "type": "paragraph",
        "content": [content_node],
    }


def create_paragraph_with_content(content: TipTapContent) -> TipTapNode:
    """Create a paragraph node with a list of content items."""
    return {
        "type": "paragraph",
        "content": content,
    }


def create_text_content(text: str, is_bold: bool = False, is_italic: bool = False) -> TipTapNode:
    """Create a text node with optional marks."""
    node: dict[str, Any] = {"type": "text", "text": text}
    marks = []
    if is_bold:
        marks.append({"type": "bold"})
    if is_italic:
        marks.append({"type": "italic"})
    if marks:
        node["marks"] = marks
    return node


def create_empty_paragraph() -> TipTapNode:
    """Create a paragraph node with no content to add spacing."""
    return {"type": "paragraph"}


def create_task_list(items: list[tuple[str, bool]]) -> TipTapNode:
    """Create a bullet list with checkbox-style items.

    Args:
        items: List of tuples (task_text, is_completed)
    """
    list_items = []
    for task_text, is_completed in items:
        checkbox = "[x]" if is_completed else "[ ]"
        task_content = f"{checkbox} {task_text}"
        list_items.append({"type": "listItem", "content": [create_paragraph_with_text(task_content)]})

    return {"type": "bulletList", "content": list_items}


def sanitize_text_content(text: str) -> str:
    """Sanitize text content to ensure it's valid for TipTap editor."""
    if not text or not text.strip():
        raise ValueError("Empty text should not be passed to create heading or paragraph")
    return text.strip()
