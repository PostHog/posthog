"""
HTML -> markdown-ish plain text normalization for URL-backed knowledge sources.

Primary extractor is trafilatura — it's specifically designed to strip
boilerplate (nav, footer, cookie banners) from article-style pages while
preserving semantic structure. Falls back to BeautifulSoup for pages where
trafilatura returns nothing (error pages, SPA shells, very minimal HTML).

Output is markdown: blocks are separated by blank lines (which the chunker
in `logic.py` relies on as paragraph boundaries) and headings/lists/code
survive extraction, which improves both chunk boundaries and retrieval.

Only `logic.py` is allowed to import this module.
"""

from __future__ import annotations

import re

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)

_CHARSET_RE = re.compile(r"charset=[\"']?([\w.-]+)", re.IGNORECASE)

# Boilerplate containers stripped before text extraction in the bs4 fallback.
# script/style/etc carry no prose; nav/header/footer/aside/form/button are the
# classic nav-bar / cookie-banner / footer-link noise we must keep out of
# searchable content.
_FALLBACK_DROP_TAGS = (
    "script",
    "style",
    "template",
    "noscript",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
)


def _decode(body: bytes, content_type: str | None) -> str:
    """
    Decode a response body for the bs4 fallback paths. Honors the charset
    declared in the Content-Type header when present and valid; otherwise
    utf-8 with errors='replace' as the floor — we'd rather get partial
    garbled text than drop the whole page. (trafilatura is fed raw bytes
    and does its own encoding detection.)
    """

    if content_type:
        match = _CHARSET_RE.search(content_type)
        if match:
            try:
                return body.decode(match.group(1))
            except (UnicodeDecodeError, LookupError):
                pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("utf-8", errors="replace")


def _bs4_fallback(html: str) -> str:
    """
    Last-resort extractor. Strips boilerplate containers (nav, header,
    footer, ...) plus script/style nodes, prefers <main>/<article> when the
    page has one, then collapses runs of whitespace. We never return raw
    attributes or inline event handlers — those are prompt-injection vectors
    when shown to the LLM.
    """

    soup = BeautifulSoup(html, "html.parser")
    for node in soup(_FALLBACK_DROP_TAGS):
        node.decompose()
    root = soup.find("main") or soup.find("article") or soup
    text = root.get_text(separator="\n")
    # Collapse whitespace runs without losing paragraph breaks.
    lines = [line.strip() for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return joined


def parse_html(body: bytes, url: str, content_type: str | None = None) -> tuple[str, str]:
    """
    Extract (title, text) from an HTML response body.

    `content_type` is the raw Content-Type header, used for charset hints in
    the fallback paths.

    Returns empty strings if extraction produced nothing usable — callers
    should treat that as a soft failure and store an error on the source.
    """

    # Deferred import: trafilatura (and its dateparser/htmldate deps) is slow to import
    # and only needed when actually parsing a page, not at API/module load.
    import trafilatura

    # trafilatura.extract returns the main-content text only. We pass raw
    # bytes so its internal encoding detection runs (meta charset, BOM, ...)
    # instead of forcing utf-8. Markdown output keeps blank lines between
    # blocks — the chunker's paragraph boundary — and preserves headings.
    extracted = trafilatura.extract(
        body,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        output_format="markdown",
    )

    title = ""
    try:
        metadata = trafilatura.extract_metadata(body)
        if metadata and metadata.title:
            title = metadata.title.strip()[:512]
    except Exception:  # noqa: BLE001 — trafilatura metadata parsing can crash on malformed HTML
        logger.info("business_knowledge.html_parse.metadata_failed", url=url)

    html: str | None = None
    text = (extracted or "").strip()
    if not text:
        try:
            html = _decode(body, content_type)
            text = _bs4_fallback(html)
        except Exception:  # noqa: BLE001 — bs4 is a best-effort fallback
            logger.info("business_knowledge.html_parse.bs4_failed", url=url)
            text = ""

    if not title:
        # Extract a title from <title> as a secondary fallback — some pages
        # have no og:title / articleTitle but do have <title>.
        try:
            if html is None:
                html = _decode(body, content_type)
            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()[:512]
        except Exception:  # noqa: BLE001
            pass

    return title, text
