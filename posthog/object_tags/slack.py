"""Rewrite agent object tags into markdown Slack can show.

Agents cite PostHog objects with XML-style tags (``<insight id="9pQx3">checkout funnel</insight>``,
``<hogql display="block" title="DAU">SELECT ...</hogql>``). The desktop and web task views parse
those into chips and chart cards; Slack has no renderer, so a raw tag reaches the thread as
escaped XML. This module runs before markdown conversion and turns each tag into the closest
thing Slack has: a link to the object, a fenced SQL block, or just the label.

The kind registry comes from ``kinds.py`` beside this module, the same source of truth the
desktop and web renderers are generated from.
"""

import re

from posthog.dataclasses import frozen
from posthog.object_tags.kinds import (
    OBJECT_KIND_ALIASES,
    OBJECT_KINDS,
    ObjectKindSpec,
    object_web_path,
    resolve_object_kind,
)

# Slack keeps a link's URL out of the message text limit, but the chat API rejects URLs past
# this size, and a SQL editor deep link carries the whole query in the query string.
_MAX_LINK_URL_LENGTH = 2000

# Links we post ourselves carry this so PostHog's own unfurler leaves inline references alone;
# a block-display reference keeps unfurling on because the unfurl card is the nearest thing
# Slack has to the chart card the desktop renders.
_UNFURL_OPT_OUT_QUERY = "unfurl=false"

_RE_OPEN_TAG = re.compile(r"<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*\"[^\"]*\")*)\s*(/>|>)")
_RE_CLOSE_TAG = re.compile(r"</([a-z][\w-]*)\s*>")
_RE_ATTR = re.compile(r"([a-z][\w-]*)\s*=\s*\"([^\"]*)\"")
_RE_FENCE_LINE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_RE_BACKTICK_RUN = re.compile(r"`+")
_RE_LABEL_UNSAFE = re.compile(r"[\[\]|]")
_LABEL_ANGLE_ENTITIES = {"<": "&lt;", ">": "&gt;"}
_RE_BARE_ID = re.compile(r"^[\w$.:-]{1,64}$")
_RE_TRAILING_LIST_MARKER = re.compile(r"(^|\n)[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])[ \t]*$")
_RE_ID_ATTR = re.compile(r"(?:^|\s)id\s*=")
_RE_PARTIAL_OPEN_TAG = re.compile(r"<(?:[a-z][\w-]*(?:\s[^>]*)?)?")

_HOGQL_SPEC = OBJECT_KINDS["hogql"]


# Only the five entities the desktop composer's XML serializer emits (``escapeXmlAttr``); the full
# HTML entity table would rewrite SQL literals such as ``'&copy;'``.
_XML_ENTITIES = {"&quot;": '"', "&apos;": "'", "&lt;": "<", "&gt;": ">", "&amp;": "&"}
_RE_XML_ENTITY = re.compile("|".join(re.escape(entity) for entity in _XML_ENTITIES))


def _unescape_xml(value: str) -> str:
    return _RE_XML_ENTITY.sub(lambda match: _XML_ENTITIES[match.group(0)], value)


@frozen
class _Span:
    start: int
    end: int

    def contains(self, position: int) -> bool:
        return self.start <= position < self.end


@frozen
class _Tag:
    name: str
    attrs: dict[str, str]
    body: str
    start: int
    end: int


def _parse_attrs(raw: str) -> dict[str, str]:
    return {match.group(1): _unescape_xml(match.group(2)) for match in _RE_ATTR.finditer(raw)}


def _inline_code_spans(line: str, offset: int) -> list[_Span]:
    """CommonMark inline code on one line: a run of N backticks closes on the next run of exactly N."""
    runs = list(_RE_BACKTICK_RUN.finditer(line))
    spans: list[_Span] = []
    index = 0
    while index < len(runs):
        opener = runs[index]
        length = opener.end() - opener.start()
        closer_index = next(
            (i for i in range(index + 1, len(runs)) if runs[i].end() - runs[i].start() == length),
            None,
        )
        if closer_index is None:
            index += 1
            continue
        spans.append(_Span(start=offset + opener.start(), end=offset + runs[closer_index].end()))
        index = closer_index + 1
    return spans


def _scan_code(text: str) -> tuple[list[_Span], int | None]:
    """Fenced blocks and inline code in one pass, plus the start of an unclosed fence.

    Mirrors the desktop renderer's fence rules: a backtick or tilde fence of three or more, closed
    only by a run of the same character at least as long with nothing else on the line, and an
    unclosed fence runs to the end of the text. The held-suffix logic needs the unclosed fence's
    start, so the walker returns it rather than a second walker recomputing the fence state.
    """
    spans: list[_Span] = []
    fence_char = ""
    fence_length = 0
    fence_start = 0
    offset = 0
    for line in text.split("\n"):
        fence = _RE_FENCE_LINE.match(line)
        if fence_char:
            closes = (
                fence is not None
                and fence.group(1)[0] == fence_char
                and len(fence.group(1)) >= fence_length
                and line[fence.end() :].strip() == ""
            )
            if closes:
                spans.append(_Span(start=fence_start, end=offset + len(line)))
                fence_char = ""
        elif fence:
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            fence_start = offset
        else:
            spans.extend(_inline_code_spans(line, offset))
        offset += len(line) + 1
    if fence_char:
        spans.append(_Span(start=fence_start, end=len(text)))
        return spans, fence_start
    return spans, None


def _scan_tags(text: str, skip_spans: list[_Span]) -> list[_Tag]:
    """Find complete tags in ``text`` in order, without overlaps.

    Openers that start inside ``skip_spans`` (code) are not tags. A tag whose closer never
    arrives is not a tag either: the text stays as it was, which matches the desktop renderer
    leaving an unterminated tag alone. Closers are indexed up front so each opener costs one
    cursor advance instead of a scan to the end of the message.
    """
    closers: dict[str, list[re.Match[str]]] = {}
    for close in _RE_CLOSE_TAG.finditer(text):
        closers.setdefault(close.group(1), []).append(close)
    cursors: dict[str, int] = {}
    tags: list[_Tag] = []
    next_allowed = 0
    span_cursor = 0
    for match in _RE_OPEN_TAG.finditer(text):
        start = match.start()
        # Openers and spans are both in text order, so the span cursor only moves forward.
        while span_cursor < len(skip_spans) and skip_spans[span_cursor].end <= start:
            span_cursor += 1
        if start < next_allowed or (span_cursor < len(skip_spans) and skip_spans[span_cursor].contains(start)):
            continue
        name = match.group(1)
        attrs = _parse_attrs(match.group(2))
        open_end = match.end()
        if match.group(3) == "/>":
            tags.append(_Tag(name=name, attrs=attrs, body="", start=start, end=open_end))
            next_allowed = open_end
            continue
        candidates = closers.get(name, [])
        cursor = cursors.get(name, 0)
        while cursor < len(candidates) and candidates[cursor].start() < open_end:
            cursor += 1
        cursors[name] = cursor
        if cursor >= len(candidates):
            continue
        close = candidates[cursor]
        tags.append(_Tag(name=name, attrs=attrs, body=text[open_end : close.start()], start=start, end=close.end()))
        next_allowed = close.end()
    return tags


def _escape_angles(text: str) -> str:
    """Entity-encode angle brackets so agent-written text cannot post a Slack broadcast.

    Slack reads ``<!channel>`` and ``<!here>`` as live mentions. An agent composes this text,
    and an agent summarizes data it was asked to analyze, so the brackets never reach Slack
    as typed.
    """
    return "".join(_LABEL_ANGLE_ENTITIES.get(char, char) for char in text)


def _safe_label(label: str) -> str:
    # The label ends up inside a Slack ``<url|label>`` link, where ``|`` and ``>`` end the link
    # early, and inside a markdown ``[label](url)`` on the way there, where brackets do. Angle
    # brackets are common in titles (``Error rate > 1%``), so they become the entities Slack
    # renders back as the characters.
    collapsed = " ".join(_RE_LABEL_UNSAFE.sub(" ", label).split())
    return _escape_angles(collapsed)


def _link(label: str, url: str | None) -> str:
    if url is None or len(url) > _MAX_LINK_URL_LENGTH:
        return label
    return f"[{label}]({url})"


def _object_url(project_url: str, kind: ObjectKindSpec, object_id: str, *, unfurl: bool) -> str | None:
    path = object_web_path(kind, object_id)
    if path is None:
        return None
    if unfurl:
        return f"{project_url}{path}"
    separator = "&" if "?" in path else "?"
    return f"{project_url}{path}{separator}{_UNFURL_OPT_OUT_QUERY}"


def _render_hogql(tag: _Tag, project_url: str) -> str | None:
    # A body written by the desktop composer is XML-escaped, so ``&lt;`` is a ``<`` in the SQL.
    sql = _unescape_xml(tag.body).strip()
    if not sql:
        return None
    url = _object_url(project_url, _HOGQL_SPEC, sql, unfurl=False)
    if tag.attrs.get("display") != "block":
        label = _safe_label(tag.attrs.get("label") or tag.attrs.get("title") or "") or _HOGQL_SPEC.kind_label
        return _link(label, url)

    title = _safe_label(tag.attrs.get("title") or "") or _HOGQL_SPEC.kind_label
    # No language hint on the fence: Slack shows one as literal text inside the block.
    # A backtick run in the SQL at least as long as the fence would close it early and
    # spill the rest — including a live ``<!channel>`` an agent could be induced to
    # write — outside the code block.
    longest_run = max((len(run.group(0)) for run in _RE_BACKTICK_RUN.finditer(sql)), default=0)
    fence = "`" * max(3, longest_run + 1)
    lines = [f"**{_link(title, url)}**", fence, sql, fence]
    caption = _escape_angles(" ".join((tag.attrs.get("caption") or "").split()))
    if caption:
        lines.append(f"_{caption}_")
    return "\n".join(lines)


def _render_reference(tag: _Tag, kind: ObjectKindSpec, project_url: str) -> str | None:
    object_id = (tag.attrs.get("id") or "").strip()
    body = tag.body.strip()
    if not object_id and _RE_BARE_ID.match(body):
        # The older ``<insight>abc123</insight>`` form Max's notebook tools still write.
        object_id, body = body, ""
    if not object_id:
        # A tag with a title but no id (a notebook query node) has no page to link; keep the title.
        return _safe_label(tag.attrs.get("title") or "") or None
    is_block = tag.attrs.get("display") == "block"
    label = _safe_label(tag.attrs.get("title") or body) or f"{kind.kind_label} {_safe_label(object_id)}"
    return _link(label, _object_url(project_url, kind, object_id, unfurl=is_block))


def _render_tag(tag: _Tag, project_url: str) -> str | None:
    kind = resolve_object_kind(tag.name)
    if kind is None:
        # An agent sometimes extends the convention to a kind nobody renders (``<inbox id="…">``).
        # The label is still the useful part, so keep it and drop the markup.
        label = _safe_label(tag.body)
        return label if "id" in tag.attrs and label else None
    if kind.id_is_body:
        return _render_hogql(tag, project_url)
    return _render_reference(tag, kind, project_url)


def rewrite_object_tags_for_slack(text: str, *, project_url: str) -> str:
    """Replace agent object tags in ``text`` with markdown Slack can render.

    ``project_url`` is the absolute ``/project/<id>`` base every object link hangs off. Tags inside
    fenced code blocks and inline code spans stay literal, as they do in the desktop renderer.
    """
    if "<" not in text:
        return text
    base = project_url.rstrip("/")
    spans, _ = _scan_code(text)
    tags = _scan_tags(text, spans)
    if not tags:
        return text
    output = ""
    position = 0
    needs_paragraph_break = False
    for tag in tags:
        rendered = _render_tag(tag, base)
        if rendered is None:
            continue
        before = text[position : tag.start]
        if needs_paragraph_break:
            # The fence must end its line, so anything after it starts a new paragraph.
            before = "\n\n" + before.lstrip("\n")
        needs_paragraph_break = False
        output += before
        if "\n" in rendered:
            # A fenced block only survives markdown conversion as its own paragraph.
            # A list marker whose only content is this block would be left as an empty
            # bullet once the block moves out, so the bare marker goes too.
            output = _RE_TRAILING_LIST_MARKER.sub(r"\1", output)
            if output.strip() and not output.endswith("\n\n"):
                output = output.rstrip("\n") + "\n\n"
            needs_paragraph_break = True
        output += rendered
        position = tag.end
    rest = text[position:]
    if needs_paragraph_break and rest.strip():
        rest = "\n\n" + rest.lstrip("\n")
    return output + rest


# A streamed flush that ends inside a tag would post the fragments as raw XML; hold back at most
# this much so a genuinely unterminated tag still flushes eventually.
_MAX_HELD_SUFFIX = 4000


@frozen
class StreamSplit:
    """A streamed chunk split into the part safe to post now and an incomplete trailing tag."""

    sendable: str
    held: str


_KNOWN_TAG_NAMES = [*OBJECT_KINDS, *OBJECT_KIND_ALIASES]


def _in_span(position: int, spans: list[_Span]) -> bool:
    return any(span.contains(position) for span in spans)


def _partial_could_become_tag(fragment: str) -> bool:
    """Could this partial tag fragment still become a tag the renderer would touch?

    Either the name so far is a prefix of a registered kind, or the fragment already
    carries an ``id`` attribute (the object-shaped improvisations the renderer keeps
    the label of). Anything else — ``plain <widget`` — is prose.
    """
    match = re.match(r"<([a-z][\w-]*)", fragment)
    name = match.group(1) if match else ""
    if re.search(r"\s", fragment):
        # The name is complete; only the attributes are still streaming.
        return resolve_object_kind(name) is not None or _RE_ID_ATTR.search(fragment[1 + len(name) :]) is not None
    return any(known.startswith(name) for known in _KNOWN_TAG_NAMES)


def split_incomplete_tag_suffix(text: str) -> StreamSplit:
    """Split off a trailing object tag, or code fence, that has not finished arriving.

    Used between streaming flushes so a tag split across two chunks is rewritten whole in the
    next one, and a tag inside a still-open fence is not rewritten at all. The whole text can be
    held; the caller then waits for more instead of posting. Unlike the web rewriter, an open
    fence is held: the splitter is stateless across flushes, so the fence's closer has to arrive
    into the same buffer for the rewrite to see the fence whole.

    Only the region after the last complete tag is considered, so tag-shaped text inside a
    complete tag's body — SQL quoting ``'<insight id="x">'`` — never splits the text. Openers
    inside code spans are prose, not streaming tags.
    """
    spans, held_from = _scan_code(text)
    search_from = 0
    if held_from is None:
        tags = _scan_tags(text, spans)
        if tags:
            search_from = tags[-1].end
    last_lt = text.rfind("<")
    if held_from is not None:
        pass
    elif (
        last_lt >= search_from
        and not _in_span(last_lt, spans)
        and ">" not in text[last_lt:]
        and _RE_PARTIAL_OPEN_TAG.fullmatch(text[last_lt:])
        and _partial_could_become_tag(text[last_lt:])
    ):
        held_from = last_lt
    else:
        last_open = None
        for match in _RE_OPEN_TAG.finditer(text):
            if match.start() < search_from or match.group(3) != ">" or _in_span(match.start(), spans):
                continue
            if resolve_object_kind(match.group(1)) is not None or _RE_ID_ATTR.search(match.group(2)):
                last_open = match
        if (
            last_open is not None
            and re.search(rf"</{re.escape(last_open.group(1))}\s*>", text[last_open.end() :]) is None
        ):
            held_from = last_open.start()
    if held_from is None or len(text) - held_from > _MAX_HELD_SUFFIX:
        return StreamSplit(sendable=text, held="")
    return StreamSplit(sendable=text[:held_from], held=text[held_from:])
