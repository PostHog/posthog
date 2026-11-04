"""Markdown to the TipTap document the support widget renders.

The widget styles ``rich_content`` and prints ``content`` as plain text.
A markdown reply with no document shows ``**bold**`` and ``[label](url)`` to the customer.
"""

from __future__ import annotations

import re

_UL_ITEM = re.compile(r"^\s*[-*]\s+")
_OL_ITEM = re.compile(r"^\s*\d+\.\s+")
_HEADING_LINE = re.compile(r"^#{1,6}\s+")
_UNSAFE_URL = re.compile("[\x00-\x1f\x7f\u200b-\u200d\ufeff]")
# A help-center paste quoted into a reply must not build a node per character
# while the ticket row is locked.
_MAX_PARSED_CHARS = 100_000


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
    if len(text) > _MAX_PARSED_CHARS:
        return [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]

    lines = text.split("\n")
    nodes: list[dict] = []
    i = 0

    while i < len(lines):
        start = i
        line = lines[i]

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

        kind = _list_kind(line)
        if kind is not None:
            list_node, i = _read_list(lines, i, kind[0], kind[1], hard_breaks=hard_breaks)
            nodes.append(list_node)
            continue

        if not line.strip():
            i += 1
            continue

        para_lines: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_special_line(lines[i]):
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            nodes.append(_paragraph(_join_lines(para_lines, hard_breaks=hard_breaks)))
        # `## ` matches a heading line but not a heading with text. Leaving i
        # here spins inside the ticket-row lock.
        if i == start:
            nodes.append(_paragraph(_parse_inline(lines[i])))
            i += 1

    return nodes


def _leading_indent(line: str) -> int:
    width = 0
    for char in line:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4
        else:
            break
    return width


def _list_kind(line: str) -> tuple[str, int] | None:
    if _UL_ITEM.match(line):
        return "bulletList", _leading_indent(line)
    if _OL_ITEM.match(line):
        return "orderedList", _leading_indent(line)
    return None


def _is_special_line(line: str) -> bool:
    if line.strip().startswith("```"):
        return True
    if _HEADING_LINE.match(line):
        return True
    return _list_kind(line) is not None


def _read_list(
    lines: list[str],
    i: int,
    list_type: str,
    base_indent: int,
    *,
    hard_breaks: bool,
) -> tuple[dict, int]:
    """One list, including a blank line between items.

    The widget renders each orderedList from 1 and ignores a start attribute.
    A blank line between ``1.`` and ``2.`` must not open a second list.
    A more-indented list stays inside the item above it, or that item ends
    and the following step also renders as 1.
    """
    item_re = _UL_ITEM if list_type == "bulletList" else _OL_ITEM
    items: list[dict] = []
    while i < len(lines):
        if not lines[i].strip():
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            nxt = _list_kind(lines[j]) if j < len(lines) else None
            if nxt is not None and nxt[0] == list_type and nxt[1] == base_indent:
                i = j
                continue
            break
        kind = _list_kind(lines[i])
        if kind is None or kind[0] != list_type or kind[1] != base_indent:
            break
        blocks, i = _read_item_blocks(lines, i, item_re, base_indent, hard_breaks=hard_breaks)
        items.append({"type": "listItem", "content": blocks})
    return {"type": list_type, "content": items}, i


def _read_item_blocks(
    lines: list[str],
    i: int,
    item_re: re.Pattern[str],
    base_indent: int,
    *,
    hard_breaks: bool,
) -> tuple[list[dict], int]:
    parts = [item_re.sub("", lines[i], count=1)]
    i += 1
    blocks: list[dict] = []

    def flush_parts() -> None:
        if parts:
            blocks.append(_paragraph(_join_lines(parts, hard_breaks=hard_breaks)))
            parts.clear()

    while i < len(lines):
        if not lines[i].strip():
            break
        kind = _list_kind(lines[i])
        if kind is not None and kind[1] > base_indent:
            flush_parts()
            nested, i = _read_list(lines, i, kind[0], kind[1], hard_breaks=hard_breaks)
            blocks.append(nested)
            continue
        if kind is not None:
            break
        if lines[i].strip().startswith("```") or _HEADING_LINE.match(lines[i]):
            break
        parts.append(lines[i])
        i += 1
    flush_parts()
    if not blocks:
        blocks.append({"type": "paragraph"})
    return blocks, i


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
    """Bold, italic, code, and links. One left-to-right pass, no backtracking.

    A regex label of ``[`` characters retries from every bracket. A help article
    full of them would hold the reply worker for the whole attempt.
    """
    if not text:
        return []

    nodes: list[dict] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    # -1 means no closer exists at or after the cached start.
    bracket_at = -2
    failed_bracket = -2
    bold_at = -2
    code_at = -2

    def flush() -> None:
        if buf:
            nodes.append({"type": "text", "text": "".join(buf)})
            buf.clear()

    while i < n:
        if text[i] == "[":
            # A missing ] is final. Searching again from every [ is quadratic.
            if bracket_at != -1 and bracket_at < i:
                bracket_at = text.find("]", i + 1)
            # One failed destination is the same for every [ that ends at that ].
            # Re-scanning it per bracket is quadratic and holds the ticket row lock.
            if bracket_at == failed_bracket or bracket_at <= i:
                buf.append("[")
                i += 1
                continue
            taken = _take_link(text, i, bracket_at)
            if taken is None:
                failed_bracket = bracket_at
                buf.append("[")
                i += 1
                continue
            flush()
            nodes.extend(taken[0])
            i = taken[1]
            continue
        if text.startswith("**", i):
            if bold_at != -1 and bold_at < i + 2:
                bold_at = text.find("**", i + 2)
            if bold_at > i + 2:
                flush()
                nodes.append({"type": "text", "text": text[i + 2 : bold_at], "marks": [{"type": "bold"}]})
                i = bold_at + 2
                continue
        elif text[i] == "*":
            close = text.find("*", i + 1)
            if close > i + 1:
                flush()
                nodes.append({"type": "text", "text": text[i + 1 : close], "marks": [{"type": "italic"}]})
                i = close + 1
                continue
        if text[i] == "`":
            if code_at != -1 and code_at < i + 1:
                code_at = text.find("`", i + 1)
            if code_at > i + 1:
                flush()
                nodes.append({"type": "text", "text": text[i + 1 : code_at], "marks": [{"type": "code"}]})
                i = code_at + 1
                continue
        buf.append(text[i])
        i += 1

    flush()
    return nodes


def _take_link(text: str, start: int, bracket_at: int) -> tuple[list[dict], int] | None:
    """A link that begins at ``start``, or None when this ``[`` is not a link."""
    if bracket_at < start + 2 or bracket_at + 1 >= len(text) or text[bracket_at + 1] != "(":
        return None
    url_close = _markdown_link_close(text, bracket_at + 2)
    if url_close is None:
        return None
    href = _safe_href(text[bracket_at + 2 : url_close])
    if href is None:
        return None
    label = text[start + 1 : bracket_at]
    label_nodes = _parse_inline(label) or [{"type": "text", "text": label}]
    linked: list[dict] = []
    for label_node in label_nodes:
        if label_node.get("type") != "text":
            linked.append(label_node)
            continue
        marks = list(label_node.get("marks") or [])
        marks.append({"type": "link", "attrs": {"href": href}})
        linked.append({**label_node, "marks": marks})
    return linked, url_close + 1


def _markdown_link_close(text: str, url_start: int) -> int | None:
    """Index of the ``)`` that ends the destination, allowing one nested pair."""
    depth = 0
    i = url_start
    n = len(text)
    while i < n:
        char = text[i]
        if char.isspace():
            return None
        if char == "(":
            if depth == 1:
                return None
            depth = 1
        elif char == ")":
            if depth == 0:
                return i
            depth = 0
        i += 1
    return None
