from django.utils.safestring import SafeString, mark_safe

import nh3
from markdown_it import MarkdownIt

from posthog.helpers.markdown_safety import is_allowed_link_url, strip_external_links_markdown

_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("table")

# defense-in-depth on top of html=False: allow only the tags commonmark emits
_ALLOWED_EMAIL_TAGS = {
    "a",
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_ALLOWED_EMAIL_ATTRS = {"a": {"href", "title"}}


def _drop_disallowed_href(tag: str, attribute: str, value: str) -> str | None:
    if tag == "a" and attribute == "href" and not is_allowed_link_url(value):
        return None
    return value


def render_markdown_email_html(markdown: str) -> SafeString:
    """Links survive only when their target passes the link allowlist."""
    rendered = _MARKDOWN_RENDERER.render(markdown)
    # Raw HTML is disabled and nh3 removes unsafe tags and attributes before email rendering.
    # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe
    return mark_safe(
        nh3.clean(
            rendered,
            tags=_ALLOWED_EMAIL_TAGS,
            attributes=_ALLOWED_EMAIL_ATTRS,
            attribute_filter=_drop_disallowed_href,
        )
    )


def render_ai_email_html(markdown: str) -> SafeString:
    """Also defangs bare URLs in model output, at the cost of backticks around URLs inside code."""
    return render_markdown_email_html(strip_external_links_markdown(markdown))
