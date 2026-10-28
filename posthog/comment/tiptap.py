"""Markdown to the TipTap document the support widget renders.

The widget styles ``rich_content`` and prints ``content`` as plain text.
A markdown reply with no document shows ``**bold**`` and ``[label](url)`` to the customer.
"""

from __future__ import annotations

import re

_UL_ITEM = re.compile(r"^\s*[-*]\s+")
_OL_ITEM = re.compile(r"^\s*\d+\.\s+")
_UNSAFE_URL = re.compile("[\x00-\x1f\x7f\u200b-\u200d\ufeff]")


def markdown_to_tiptap_doc(text: str) -> dict[str, object]:
    # Single newlines are line breaks in a support reply. Joining them with a space
    # would glue "See [article](url)" onto the step above it.
    nodes = markdown_to_tiptap_nodes(text, hard_breaks=True)
    if not nodes:
        nodes = [{"type": "paragraph"}]
    return {"type": "doc", "content": nodes}


def markdown_to_tiptap_nodes(text: str, *, hard_breaks: bool = False) -> list[dict]:
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
        if _UL_ITEM.match(line):
            list_node, i = _read_list(lines, i, _UL_ITEM, "bulletList", hard_breaks=hard_breaks)
            nodes.append(list_node)
            continue

        # Ordered list
        if _OL_ITEM.match(line):
            list_node, i = _read_list(lines, i, _OL_ITEM, "orderedList", hard_breaks=hard_breaks)
            nodes.append(list_node)
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
            nodes.append(_paragraph(_join_lines(para_lines, hard_breaks=hard_breaks)))

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


def _read_list(
    lines: list[str],
    i: int,
    item_re: re.Pattern[str],
    list_type: str,
    *,
    hard_breaks: bool,
) -> tuple[dict, int]:
    """One list, including a blank line between items.

    The widget renders each orderedList from 1 and ignores a start attribute.
    A blank line between ``1.`` and ``2.`` must not open a second list.
    """
    items: list[dict] = []
    while i < len(lines):
        if not lines[i].strip():
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and item_re.match(lines[j]):
                i = j
                continue
            break
        if not item_re.match(lines[i]):
            break
        parts = [item_re.sub("", lines[i], count=1)]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_special_line(lines[i]):
            parts.append(lines[i])
            i += 1
        items.append({"type": "listItem", "content": [_paragraph(_join_lines(parts, hard_breaks=hard_breaks))]})
    return {"type": list_type, "content": items}, i


def _join_lines(lines: list[str], *, hard_breaks: bool) -> list[dict]:
    if not hard_breaks:
        return _parse_inline(" ".join(lines))
    nodes: list[dict] = []
    for index, line in enumerate(lines):
        if index:
            nodes.append({"type": "hardBreak"})
        nodes.extend(_parse_inline(line))
    return nodes


def _paragraph(content: list[dict]) -> dict:
    if not content:
        return {"type": "paragraph"}
    return {"type": "paragraph", "content": content}


def _safe_href(url: str) -> str | None:
    """http(s), mailto, tel, or a relative path. Anything else stays literal text.

    Email turns a link mark into an href. The widget blocks ``javascript:`` when it
    renders, but the mail body would not.
    """
    cleaned = _UNSAFE_URL.sub("", url).strip()
    if not cleaned or cleaned.startswith("//"):
        return None
    normalized = re.sub(r"\s+", "", cleaned).lower()
    if normalized.startswith(("javascript:", "vbscript:", "data:", "file:")):
        return None
    if cleaned.startswith(("/", "./", "../", "#")):
        return cleaned
    lower = cleaned.lower()
    if lower.startswith(("https://", "http://", "mailto:", "tel:")):
        return cleaned
    return None


def _parse_inline(text: str) -> list[dict]:
    """
    Parse inline markdown into tiptap text nodes with marks.

    Handles: **bold**, *italic*, `code`, [text](url)
    """
    if not text:
        return []

    nodes: list[dict] = []
    # Link first so [**label**](url) stays one link, with bold parsed inside the label.
    pattern = re.compile(
        # One level of parentheses, so alert(1) does not end the destination early.
        r"\[([^\]]+)\]\(([^()\s]*(?:\([^()\s]*\)[^()\s]*)*)\)"
        r"|(\*\*(.+?)\*\*)"  # bold
        r"|(\*(.+?)\*)"  # italic
        r"|(`(.+?)`)"  # inline code
    )

    pos = 0
    for match in pattern.finditer(text):
        # Add preceding plain text
        if match.start() > pos:
            plain = text[pos : match.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})

        if match.group(1) is not None:
            href = _safe_href(match.group(2))
            if href is None:
                nodes.append({"type": "text", "text": match.group(0)})
            else:
                label_nodes = _parse_inline(match.group(1)) or [{"type": "text", "text": match.group(1)}]
                for label_node in label_nodes:
                    if label_node.get("type") != "text":
                        nodes.append(label_node)
                        continue
                    marks = list(label_node.get("marks") or [])
                    marks.append({"type": "link", "attrs": {"href": href}})
                    nodes.append({**label_node, "marks": marks})
        elif match.group(4) is not None:
            # Bold
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(4),
                    "marks": [{"type": "bold"}],
                }
            )
        elif match.group(6) is not None:
            # Italic
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(6),
                    "marks": [{"type": "italic"}],
                }
            )
        elif match.group(8) is not None:
            # Inline code
            nodes.append(
                {
                    "type": "text",
                    "text": match.group(8),
                    "marks": [{"type": "code"}],
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
