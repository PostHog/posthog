import re
from typing import Any

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_ATX_CLOSE_RE = re.compile(r"[ \t]+#+[ \t]*$")


def get_markdown_outline(text: str) -> list[dict[str, Any]]:
    """Extract a flat list of markdown headings from a string.

    Returns a list of ``{"level": int, "text": str}`` dicts — one per heading.
    Useful as a lightweight table of contents for agents consuming the MCP/API.
    """
    if not text:
        return []
    outline: list[dict[str, Any]] = []
    for line in text.split("\n"):
        match = _MARKDOWN_HEADING_RE.match(line.strip())
        if not match:
            continue
        heading = _ATX_CLOSE_RE.sub("", match.group(2)).rstrip()
        if heading:
            outline.append({"level": len(match.group(1)), "text": heading})
    return outline
