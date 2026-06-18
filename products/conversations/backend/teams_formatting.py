"""Convert between Microsoft Teams HTML and PostHog rich_content format."""

import re
import html as html_mod
from typing import Any

JSON = dict[str, Any]

# Teams sends HTML content -- strip <at> tags and common formatting
_RE_AT_MENTION = re.compile(r"<at[^>]*>.*?</at>", re.IGNORECASE)
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_MULTI_NEWLINES = re.compile(r"\n{2,}")
_RE_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")


def _strip_at_mentions(html_text: str) -> str:
    """Remove <at>...</at> mention tags from Teams HTML, leaving plain text."""
    return _RE_AT_MENTION.sub("", html_text)


def _html_to_plain(html_text: str) -> str:
    """Basic HTML -> plain text: strip tags, unescape entities, normalize whitespace."""
    text = html_text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n").replace("</div>", "\n")
    text = _RE_HTML_TAG.sub("", text)
    text = html_mod.unescape(text)
    text = _RE_HORIZONTAL_WHITESPACE.sub(" ", text)
    text = _RE_MULTI_NEWLINES.sub("\n", text)
    return text.strip()


def teams_html_to_content_and_rich_content(html_text: str) -> tuple[str, JSON | None]:
    """
    Convert Teams HTML message content to PostHog content (plain text) and rich_content.

    Teams sends messages as HTML with <at> tags for mentions, basic formatting
    (<b>, <i>, <a>), and <br>/<p> for line breaks. We convert to a simple
    doc structure for PostHog's rich content model.
    """
    if not html_text:
        return "", None

    # Strip @mention tags first
    cleaned_html = _strip_at_mentions(html_text)
    plain_text = _html_to_plain(cleaned_html)

    if not plain_text.strip():
        return "", None

    # Build rich_content as a simple doc with paragraph nodes
    paragraphs = [p.strip() for p in plain_text.split("\n") if p.strip()]
    content_nodes: list[JSON] = []
    for para in paragraphs:
        content_nodes.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": para}],
            }
        )

    rich_content: JSON = {"type": "doc", "content": content_nodes} if content_nodes else {"type": "doc", "content": []}

    return plain_text, rich_content


def rich_content_to_teams_html(rich_content: JSON | None, fallback_content: str = "") -> str:
    """
    Convert PostHog rich_content to HTML suitable for Teams Bot Framework replies.

    Handles: paragraphs, text marks (bold, italic, code), links, lists, images.
    Falls back to plain text if rich_content is not available.
    """
    if not rich_content or not isinstance(rich_content, dict):
        return html_mod.escape(fallback_content)

    nodes = rich_content.get("content", [])
    if not nodes:
        return html_mod.escape(fallback_content)

    parts: list[str] = []
    for node in nodes:
        rendered = _render_node(node)
        if rendered:
            parts.append(rendered)

    return "".join(parts) or html_mod.escape(fallback_content)


def _render_node(node: JSON) -> str:
    node_type = node.get("type", "")

    if node_type == "paragraph":
        inner = _render_inline_content(node.get("content", []))
        return f"<p>{inner}</p>" if inner else ""

    if node_type == "text":
        return _render_text_node(node)

    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 2)
        inner = _render_inline_content(node.get("content", []))
        return f"<h{level}>{inner}</h{level}>"

    if node_type in ("bulletList", "bullet_list"):
        items = "".join(_render_node(child) for child in node.get("content", []))
        return f"<ul>{items}</ul>"

    if node_type in ("orderedList", "ordered_list"):
        items = "".join(_render_node(child) for child in node.get("content", []))
        return f"<ol>{items}</ol>"

    if node_type in ("listItem", "list_item"):
        inner = "".join(_render_node(child) for child in node.get("content", []))
        return f"<li>{inner}</li>"

    if node_type == "blockquote":
        inner = "".join(_render_node(child) for child in node.get("content", []))
        return f"<blockquote>{inner}</blockquote>"

    if node_type in ("codeBlock", "code_block"):
        inner = _render_inline_content(node.get("content", []))
        return f"<pre><code>{inner}</code></pre>"

    if node_type in ("horizontalRule", "horizontal_rule"):
        return "<hr/>"

    if node_type == "image":
        attrs = node.get("attrs", {})
        src = attrs.get("src", "")
        alt = html_mod.escape(attrs.get("alt", "image"))
        return f'<img src="{html_mod.escape(src)}" alt="{alt}"/>' if src else ""

    if node_type == "hardBreak":
        return "<br/>"

    # Unknown node: try to render children
    children = node.get("content", [])
    if children:
        return "".join(_render_node(child) for child in children)
    return ""


def _render_inline_content(nodes: list[JSON]) -> str:
    return "".join(_render_text_node(n) if n.get("type") == "text" else _render_node(n) for n in nodes)


def _render_text_node(node: JSON) -> str:
    text = html_mod.escape(node.get("text", ""))
    marks = node.get("marks", [])
    for mark in marks:
        mark_type = mark.get("type", "")
        if mark_type == "bold":
            text = f"<b>{text}</b>"
        elif mark_type == "italic":
            text = f"<i>{text}</i>"
        elif mark_type == "code":
            text = f"<code>{text}</code>"
        elif mark_type == "link":
            href = html_mod.escape(mark.get("attrs", {}).get("href", ""))
            text = f'<a href="{href}">{text}</a>'
        elif mark_type == "strike":
            text = f"<s>{text}</s>"
    return text
