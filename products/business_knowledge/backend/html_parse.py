"""
HTML -> plain text normalization for URL-backed knowledge sources.

Primary extractor is trafilatura — it's specifically designed to strip
boilerplate (nav, footer, cookie banners) from article-style pages while
preserving semantic structure. Falls back to BeautifulSoup for pages where
trafilatura returns nothing (error pages, SPA shells, very minimal HTML).

Only `logic.py` is allowed to import this module.
"""

from __future__ import annotations

import structlog
import trafilatura
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)


def _decode(body: bytes) -> str:
    # trafilatura handles encoding detection internally, but the bs4 fallback
    # needs us to pick something. utf-8 with errors='replace' is a sensible
    # floor — we'd rather get partial garbled text than drop the whole page.
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("utf-8", errors="replace")


def _bs4_fallback(html: str) -> str:
    """
    Last-resort extractor. Strips script/style/template nodes, then collapses
    runs of whitespace. We never return raw attributes or inline event
    handlers — those are prompt-injection vectors when shown to the LLM.
    """

    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "template", "noscript", "iframe"]):
        node.decompose()
    text = soup.get_text(separator="\n")
    # Collapse whitespace runs without losing paragraph breaks.
    lines = [line.strip() for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return joined


def parse_html(body: bytes, url: str) -> tuple[str, str]:
    """
    Extract (title, text) from an HTML response body.

    Returns empty strings if extraction produced nothing usable — callers
    should treat that as a soft failure and store an error on the source.
    """

    html = _decode(body)

    # trafilatura.extract returns the main-content text only. We ask for
    # plain output (not XML/JSON) to keep downstream chunking dead simple.
    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        output_format="txt",
    )

    title = ""
    try:
        metadata = trafilatura.extract_metadata(html)
        if metadata and metadata.title:
            title = metadata.title.strip()[:512]
    except Exception:  # noqa: BLE001 — trafilatura metadata parsing can crash on malformed HTML
        logger.info("business_knowledge.html_parse.metadata_failed", url=url)

    text = (extracted or "").strip()
    if not text:
        try:
            text = _bs4_fallback(html)
        except Exception:  # noqa: BLE001 — bs4 is a best-effort fallback
            logger.info("business_knowledge.html_parse.bs4_failed", url=url)
            text = ""

    if not title:
        # Extract a title from <title> as a secondary fallback — some pages
        # have no og:title / articleTitle but do have <title>.
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()[:512]
        except Exception:  # noqa: BLE001
            pass

    return title, text
