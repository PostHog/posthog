import re
from collections import defaultdict, deque

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark").disable("inline")
_BACKTICKS = re.compile(r"`+")


def _inline_code_spans(text: str, offset: int) -> list[range]:
    runs = list(_BACKTICKS.finditer(text))
    by_length: defaultdict[int, deque[re.Match[str]]] = defaultdict(deque)
    for run in runs:
        by_length[run.end() - run.start()].append(run)
    spans: list[range] = []
    cursor = 0
    for opener in runs:
        if opener.start() < cursor:
            continue
        escaped_from = opener.start()
        while escaped_from > 0 and text[escaped_from - 1] == "\\":
            escaped_from -= 1
        if (opener.start() - escaped_from) % 2:
            continue
        candidates = by_length[opener.end() - opener.start()]
        while candidates and candidates[0].start() <= opener.start():
            candidates.popleft()
        if candidates:
            closer = candidates[0]
            spans.append(range(offset + opener.start(), offset + closer.end()))
            cursor = closer.end()
    return spans


def markdown_code_spans(text: str) -> list[range]:
    line_offsets = [0]
    line_offsets.extend(match.end() for match in re.finditer(r"\r\n?|\n", text))
    if line_offsets[-1] != len(text):
        line_offsets.append(len(text))
    spans: list[range] = []
    cursor = 0
    for token in _MARKDOWN.parse(text):
        if token.type not in ("fence", "code_block") or token.map is None:
            continue
        start, end = (line_offsets[line] for line in token.map)
        spans.extend(_inline_code_spans(text[cursor:start], cursor))
        spans.append(range(start, end))
        cursor = end
    spans.extend(_inline_code_spans(text[cursor:], cursor))
    return spans
