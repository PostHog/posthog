"""Convert between PostHog rich content/markdown and Slack payload formats."""

import re
from collections.abc import Iterable
from typing import Any

JSON = dict[str, Any]


def content_to_slack_mrkdwn(content: str) -> str:
    """Convert markdown comment content to Slack mrkdwn text."""
    if not content:
        return ""

    text = content

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"<\2|\1>", text)

    bold_italic_matches: list[str] = []

    def capture_bold_italic(match: re.Match) -> str:
        bold_italic_matches.append(match.group(1))
        return f"\x00BI{len(bold_italic_matches) - 1}\x00"

    text = re.sub(r"\*\*\*(.+?)\*\*\*", capture_bold_italic, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"_\1_", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    for index, value in enumerate(bold_italic_matches):
        text = text.replace(f"\x00BI{index}\x00", f"*_{value}_*")

    def resolve_mention(match: re.Match) -> str:
        uuid_str = match.group(1)
        try:
            from posthog.models import User

            user = User.objects.filter(uuid=uuid_str).first()
            if user:
                name = f"{user.first_name} {user.last_name}".strip() or user.email
                return f"@{name}"
        except Exception:
            pass
        return "@teammate"

    return re.sub(r"@member:([a-f0-9-]+)", resolve_mention, text)


def slack_mrkdwn_to_content(text: str) -> str:
    """Convert Slack mrkdwn text to markdown content."""
    if not text:
        return ""

    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"[\2](\1)", text)
    text = re.sub(r"<([^>]+)>", r"\1", text)
    text = re.sub(r"\*_([^_]+)_\*", r"***\1***", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"**\1**", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"*\1*", text)

    return text


def _normalize_single_newlines_to_markdown(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"(?<!\n)\n(?!\n)", "  \n", text)


def _escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|])", r"\\\1", text)


def _escape_alt_text(text: str) -> str:
    return re.sub(r"([\\\]])", r"\\\1", text)


def _style_to_marks(style: JSON | None) -> list[JSON]:
    if not style:
        return []

    marks: list[JSON] = []
    if style.get("bold"):
        marks.append({"type": "bold"})
    if style.get("italic"):
        marks.append({"type": "italic"})
    if style.get("underline"):
        marks.append({"type": "underline"})
    if style.get("code"):
        marks.append({"type": "code"})
    return marks


def _marks_to_slack_style(marks: Iterable[JSON]) -> JSON:
    style: JSON = {}
    for mark in marks:
        mark_type = mark.get("type")
        if mark_type == "bold":
            style["bold"] = True
        elif mark_type == "italic":
            style["italic"] = True
        elif mark_type == "underline":
            style["underline"] = True
        elif mark_type == "code":
            style["code"] = True
    return style


def _append_text_with_breaks(nodes: list[JSON], text: str, marks: list[JSON]) -> None:
    if not text:
        return

    parts = text.split("\n")
    for index, part in enumerate(parts):
        if part:
            node: JSON = {"type": "text", "text": part}
            if marks:
                node["marks"] = marks
            nodes.append(node)
        if index < len(parts) - 1:
            nodes.append({"type": "hardBreak"})


def _parse_rich_text_inline_elements(elements: list[JSON]) -> list[JSON]:
    nodes: list[JSON] = []

    for element in elements:
        element_type = element.get("type")

        if element_type == "text":
            _append_text_with_breaks(nodes, element.get("text", ""), _style_to_marks(element.get("style")))
            continue

        if element_type == "link":
            url = element.get("url")
            if not url:
                continue
            marks = _style_to_marks(element.get("style"))
            marks.append({"type": "link", "attrs": {"href": url}})
            _append_text_with_breaks(nodes, element.get("text") or url, marks)
            continue

        if element_type == "emoji":
            nodes.append({"type": "text", "text": f":{element.get('name', '')}:"})
            continue

        if element_type == "user":
            nodes.append({"type": "text", "text": f"<@{element.get('user_id', '')}>"})
            continue

        if element_type == "channel":
            label = element.get("name") or element.get("channel_id", "")
            nodes.append({"type": "text", "text": f"#{label}"})
            continue

        if element_type == "broadcast":
            nodes.append({"type": "text", "text": f"@{element.get('range', 'channel')}"})
            continue

        if element.get("text"):
            _append_text_with_breaks(nodes, element.get("text", ""), _style_to_marks(element.get("style")))

    return nodes


def slack_blocks_to_rich_content(blocks: list[JSON] | None) -> JSON | None:
    """Parse Slack rich_text blocks into PostHog SupportEditor-compatible JSON."""
    if not blocks:
        return None

    doc_nodes: list[JSON] = []
    saw_rich_text = False

    for block in blocks:
        if block.get("type") != "rich_text":
            continue

        saw_rich_text = True
        for element in block.get("elements", []):
            element_type = element.get("type")

            if element_type == "rich_text_section":
                inline_nodes = _parse_rich_text_inline_elements(element.get("elements", []))
                if inline_nodes:
                    doc_nodes.append({"type": "paragraph", "content": inline_nodes})
                continue

            if element_type == "rich_text_list":
                for list_item in element.get("elements", []):
                    if list_item.get("type") != "rich_text_section":
                        continue
                    inline_nodes = _parse_rich_text_inline_elements(list_item.get("elements", []))
                    if inline_nodes:
                        prefix = "• "
                        inline_nodes.insert(0, {"type": "text", "text": prefix})
                        doc_nodes.append({"type": "paragraph", "content": inline_nodes})
                continue

            if element_type == "rich_text_preformatted":
                inline_nodes = _parse_rich_text_inline_elements(element.get("elements", []))
                if inline_nodes:
                    doc_nodes.append({"type": "paragraph", "content": inline_nodes})
                continue

            if element_type == "rich_text_quote":
                inline_nodes = _parse_rich_text_inline_elements(element.get("elements", []))
                if inline_nodes:
                    inline_nodes.insert(0, {"type": "text", "text": "> "})
                    doc_nodes.append({"type": "paragraph", "content": inline_nodes})
                continue

    if not saw_rich_text:
        return None

    return {"type": "doc", "content": doc_nodes or [{"type": "paragraph", "content": []}]}


def _serialize_text_node_to_markdown(node: JSON) -> str:
    text = node.get("text", "")
    marks = node.get("marks", [])
    has_code_mark = any(mark.get("type") == "code" for mark in marks)

    if not has_code_mark:
        text = _escape_markdown(text)

    link_mark = next((mark for mark in marks if mark.get("type") == "link"), None)

    for mark in marks:
        mark_type = mark.get("type")
        if mark_type == "bold":
            text = f"**{text}**"
        elif mark_type == "italic":
            text = f"*{text}*"
        elif mark_type == "code":
            text = f"`{text}`" if "`" not in text else f"`` {text} ``"
        # Underline has no standard markdown syntax - preserve in rich content only.

    if link_mark and link_mark.get("attrs", {}).get("href"):
        text = f"[{text}]({link_mark['attrs']['href']})"

    return text


def _serialize_inline_nodes_to_markdown(nodes: list[JSON], include_images: bool = True) -> str:
    chunks: list[str] = []
    for node in nodes:
        node_type = node.get("type")
        if node_type == "text":
            chunks.append(_serialize_text_node_to_markdown(node))
        elif node_type == "hardBreak":
            chunks.append("  \n")
        elif node_type == "image" and include_images:
            src = node.get("attrs", {}).get("src")
            if src:
                alt = _escape_alt_text(node.get("attrs", {}).get("alt", "image"))
                chunks.append(f"![{alt}]({src})")
    return "".join(chunks)


def rich_content_to_markdown(rich_content: JSON | None, include_images: bool = True) -> str:
    """Serialize PostHog rich content JSON to markdown text."""
    if not rich_content:
        return ""

    root_type = rich_content.get("type")
    if root_type != "doc":
        return ""

    blocks: list[str] = []
    for node in rich_content.get("content", []):
        node_type = node.get("type")

        if node_type == "paragraph":
            blocks.append(_serialize_inline_nodes_to_markdown(node.get("content", []), include_images=include_images))
            continue

        if node_type == "image" and include_images:
            src = node.get("attrs", {}).get("src")
            if src:
                alt = _escape_alt_text(node.get("attrs", {}).get("alt", "image"))
                blocks.append(f"![{alt}]({src})")

    return "\n\n".join(blocks).strip()


def _text_node_to_slack_elements(node: JSON) -> list[JSON]:
    text = node.get("text", "")
    if not text:
        return []

    marks = node.get("marks", [])
    link_mark = next((mark for mark in marks if mark.get("type") == "link"), None)
    style = _marks_to_slack_style(mark for mark in marks if mark.get("type") != "link")

    if link_mark and link_mark.get("attrs", {}).get("href"):
        element: JSON = {"type": "link", "url": link_mark["attrs"]["href"], "text": text}
    else:
        element = {"type": "text", "text": text}

    if style:
        element["style"] = style
    return [element]


def extract_images_from_rich_content(rich_content: JSON | None) -> list[JSON]:
    if not rich_content or rich_content.get("type") != "doc":
        return []

    images: list[JSON] = []
    for node in rich_content.get("content", []):
        node_type = node.get("type")
        if node_type == "image":
            src = node.get("attrs", {}).get("src")
            if src:
                images.append({"url": src, "alt": node.get("attrs", {}).get("alt", "image")})
            continue
        if node_type == "paragraph":
            for child in node.get("content", []):
                if child.get("type") == "image":
                    src = child.get("attrs", {}).get("src")
                    if src:
                        images.append({"url": src, "alt": child.get("attrs", {}).get("alt", "image")})
    return images


def rich_content_to_slack_blocks(rich_content: JSON | None, include_images: bool = True) -> list[JSON] | None:
    """Serialize PostHog rich content JSON into Slack rich_text blocks."""
    if not rich_content or rich_content.get("type") != "doc":
        return None

    rich_text_elements: list[JSON] = []

    for node in rich_content.get("content", []):
        node_type = node.get("type")

        if node_type == "paragraph":
            section_elements: list[JSON] = []
            for child in node.get("content", []):
                child_type = child.get("type")
                if child_type == "text":
                    section_elements.extend(_text_node_to_slack_elements(child))
                elif child_type == "hardBreak":
                    section_elements.append({"type": "text", "text": "\n"})
                elif child_type == "image" and include_images:
                    src = child.get("attrs", {}).get("src")
                    if src:
                        alt = child.get("attrs", {}).get("alt", "image")
                        section_elements.append({"type": "link", "url": src, "text": alt})

            if section_elements:
                rich_text_elements.append({"type": "rich_text_section", "elements": section_elements})
            continue

        if node_type == "image" and include_images:
            src = node.get("attrs", {}).get("src")
            if src:
                rich_text_elements.append(
                    {
                        "type": "rich_text_section",
                        "elements": [{"type": "link", "url": src, "text": node.get("attrs", {}).get("alt", "image")}],
                    }
                )

    if not rich_text_elements:
        return None

    return [{"type": "rich_text", "elements": rich_text_elements}]


def slack_to_content_and_rich_content(text: str, blocks: list[JSON] | None = None) -> tuple[str, JSON | None]:
    """
    Convert inbound Slack payload to markdown content and rich_content.

    Priority:
    1. Slack rich_text blocks (for style fidelity including underline and nested marks)
    2. text/mrkdwn fallback
    """
    parsed_rich_content = slack_blocks_to_rich_content(blocks)
    if parsed_rich_content:
        markdown_content = rich_content_to_markdown(parsed_rich_content)
        return markdown_content, parsed_rich_content

    markdown_content = slack_mrkdwn_to_content(text)
    return _normalize_single_newlines_to_markdown(markdown_content), None


def rich_content_to_slack_payload(
    rich_content: JSON | None, fallback_content: str, include_images: bool = True
) -> tuple[str, list[JSON] | None]:
    """
    Convert outbound app message to Slack payload fields.

    Returns:
    - text (always present, used as fallback for notifications/older clients)
    - blocks (Slack rich_text blocks when rich_content is available)
    """
    if rich_content:
        blocks = rich_content_to_slack_blocks(rich_content, include_images=include_images)
        if blocks:
            markdown_text = rich_content_to_markdown(rich_content, include_images=include_images)
            source_content = markdown_text or fallback_content
            return content_to_slack_mrkdwn(source_content), blocks

    return content_to_slack_mrkdwn(fallback_content), None
