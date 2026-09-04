"""Keep inbound-email hyperlinks intact all the way to the inbox.

Two things break links between Mailgun and the rendered message:

1. Mailgun builds `body-plain` for an HTML-only email by stripping tags, which
   keeps the anchor text but loses the `href`. A call-to-action link (for example
   an email forwarding activation link) never reaches the inbox. We read the links
   back out of `body-html` and fold them into the stored text as Markdown.
2. The inbox renders message text with GFM autolink literals, which trim trailing
   punctuation (`~`, `.`, `?`, ...) from a bare URL. Click-tracking links such as
   Mailgun/SparkPost `.../<token>~` end in that punctuation, so the rendered link
   loses its last character and no longer resolves. We wrap bare URLs in angle
   brackets so the renderer takes them verbatim.

The stripped body is kept as-is, so quoted-reply trimming and threading are
unaffected.
"""

from __future__ import annotations

import re

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)

_HTTP_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
# Sentence punctuation that trails a URL in prose but is never part of an opaque
# tracking token (base64url uses `-`/`_`, SparkPost ends in `~`). Trimmed before
# wrapping so a URL ending a sentence does not carry the punctuation into the link.
_URL_TRAILING_PUNCTUATION = ".,;:!?"
# Cap the anchors we scan so a large marketing email can't turn one message into
# an expensive parse.
_MAX_ANCHORS = 100
# A bare URL, scanned in one linear pass so a hostile body can't force quadratic
# work. The class keeps parentheses so a URL like `.../Markdown_(language)` stays
# whole; any unbalanced trailing parenthesis (from a `(url)` wrapper) is peeled back
# off in `_wrap_bare_urls`.
_BARE_URL_RE = re.compile(r"https?://[^\s<>\[\]]+", re.IGNORECASE)


def _md_safe_href(href: str) -> str:
    """Escape the characters that would end a Markdown link destination early."""
    return href.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def recover_links_from_html(text: str, html: str) -> str:
    """Recover links lost by flattening, then keep every URL whole for the renderer.

    First fold any anchor whose `href` was dropped from `text` back in as Markdown,
    then wrap the remaining bare URLs so the Markdown renderer keeps them intact.
    """
    if not text:
        return text
    recovered = _recover_from_html(text, html) if html else text
    return _wrap_bare_urls(recovered)


def _wrap_bare_urls(text: str) -> str:
    """Wrap bare URLs in angle brackets so the Markdown renderer keeps them whole.

    The inbox renders message text with GFM autolink literals, which trim trailing
    punctuation from a bare URL. An explicit `<url>` autolink is taken verbatim, so
    the full token survives. A URL already inside an angle autolink or a Markdown
    link (as its destination or its text) is left as-is.

    Sentence punctuation and an unbalanced trailing parenthesis are peeled off the
    end and left outside the link, so a URL ending a sentence or wrapped in `(...)`
    stays clean while a balanced `(...)` inside the URL is kept. Token characters
    (`~`, `-`, `_`) are kept, since dropping one would break the links this protects.

    The whole pass is linear: URLs are found with a single non-backtracking scan and
    protection is an O(1) look-behind, so a hostile body cannot force quadratic work.
    """

    def is_protected(start: int) -> bool:
        # `<url…` is an angle autolink; `[url…` is link text; `](url…` is a link
        # destination. Any of these means the URL is already linked — leave it be.
        if start > 0 and text[start - 1] in "<[":
            return True
        return start >= 2 and text[start - 2 : start] == "]("

    result: list[str] = []
    last = 0
    for match in _BARE_URL_RE.finditer(text):
        start, end = match.span()
        if is_protected(start):
            continue
        url = match.group(0)
        # Count parentheses once, then walk back from the end in a single pass so a
        # long run of trailing ")" or punctuation stays O(len(url)).
        open_count = url.count("(")
        close_count = url.count(")")
        stop = len(url)
        while stop > 0:
            char = url[stop - 1]
            if char in _URL_TRAILING_PUNCTUATION:
                pass
            elif char == ")" and close_count > open_count:
                close_count -= 1
            else:
                break
            stop -= 1
        core = url[:stop]
        scheme = _HTTP_SCHEME_RE.match(core)
        # Nothing left after the scheme (e.g. "https://.") — leave the text alone.
        if not scheme or len(core) == scheme.end():
            continue
        result.append(text[last:start])
        result.append(f"<{core}>{url[stop:]}")
        last = end
    result.append(text[last:])
    return "".join(result)


def _recover_from_html(text: str, html: str) -> str:
    """Fold links from `html` into `text` as Markdown when they were lost.

    Only a link whose URL is missing from `text` and whose anchor text still
    appears verbatim in `text` is rewritten, once, to `[label](href)`. Anything
    else is left untouched, so already-linked URLs and stripped quotes are safe.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 — a malformed HTML part must never fail ingestion
        logger.info("conversations.email_links.parse_failed")
        return text

    candidates: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for anchor in soup.find_all("a")[:_MAX_ANCHORS]:
        href = (anchor.get("href") or "").strip()
        if not href or not _HTTP_SCHEME_RE.match(href):
            continue
        label = anchor.get_text(separator=" ", strip=True)
        # Skip an unusable label, a URL that already survived into the text, or a
        # label seen already (its first anchor wins).
        if not label or "[" in label or "]" in label or href in text or label in seen_labels:
            continue
        seen_labels.add(label)
        candidates.append((label, href))

    if not candidates:
        return text

    # Rewrite left to right on the not-yet-emitted suffix only, so a later label
    # can never match inside a link or URL we already inserted. Each pass links
    # the earliest remaining label occurrence; earliest position wins on ties.
    parts: list[str] = []
    remaining = text
    used: set[str] = set()
    while True:
        best: tuple[int, str, str] | None = None
        for label, href in candidates:
            if label in used:
                continue
            index = remaining.find(label)
            if index != -1 and (best is None or index < best[0]):
                best = (index, label, href)
        if best is None:
            break
        index, label, href = best
        parts.append(remaining[:index])
        parts.append(f"[{label}]({_md_safe_href(href)})")
        remaining = remaining[index + len(label) :]
        used.add(label)
    parts.append(remaining)

    return "".join(parts)
