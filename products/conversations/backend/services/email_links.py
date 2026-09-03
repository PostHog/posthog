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
# Cap the anchors we scan so a large marketing email can't turn one message into
# an expensive parse.
_MAX_ANCHORS = 100
# Match an existing Markdown link/image or angle autolink first so we skip over it,
# then a bare URL (delimited by whitespace, brackets, or parentheses) to wrap.
_LINKIFY_RE = re.compile(
    r"(?P<mdlink>!?\[[^\]]*\]\([^)]*\))"
    r"|(?P<autolink><[^<>\s]+>)"
    r"|(?P<bare>https?://[^\s<>()\[\]]+)",
    re.IGNORECASE,
)


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
    the full token survives. Existing Markdown links and autolinks are left as-is.

    The whole matched URL is wrapped without trimming trailing characters: a
    tracking token is opaque and can legitimately end in `~`, `-`, or `_`, so
    dropping a trailing character would break the very links this protects.
    """

    def replace(match: re.Match[str]) -> str:
        bare = match.group("bare")
        return f"<{bare}>" if bare else match.group(0)

    return _LINKIFY_RE.sub(replace, text)


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
