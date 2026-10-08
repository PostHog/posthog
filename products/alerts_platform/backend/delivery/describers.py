"""How each source words its own notifications.

The platform imports no source, so a source registers its describer here when Django starts, the
way `products.alerts` registers its destination resolver.
"""

from typing import Final

import structlog

from posthog.slack.channels import clip_text

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    SourceDescriber,
    SourceDescription,
    SourceKind,
)
from products.alerts_platform.backend.temporal.metrics import increment_describer_failures, safe_record

# A source's context names things a user chose, such as services, so its size is unbounded. The
# bound is set once here, so every transport's own budget starts from the same small print.
MAX_CONTEXT_LINES: Final = 3
MAX_CONTEXT_LINE_CHARS: Final = 300
# A data link can carry a whole filter in its query string. Slack refuses a post whose button URL is
# over 3000 characters, so a longer link is dropped rather than costing the message.
MAX_DATA_LINK_URL_CHARS: Final = 2000

logger = structlog.get_logger(__name__)

_describers: dict[SourceKind, SourceDescriber] = {}


def register(source: SourceKind, describer: SourceDescriber) -> None:
    # One owner per source. A second registrant would silently reword another product's alerts.
    registered = _describers.get(source)
    if registered is not None and registered is not describer:
        raise RuntimeError(f"A different describer is already registered for {source} alerts.")
    _describers[source] = describer


def describe(source: SourceKind, *, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    """The source's own words for a transition, or an empty description.

    Empty when nothing is registered, because the platform's wording is a complete message, so a
    source without a describer still delivers.
    """
    describer = _describers.get(source)
    if describer is None:
        return SourceDescription()
    try:
        description = describer(project_id=project_id, transition=transition)
    except Exception:
        # The wording is never worth a lost notification. The platform's own wording goes out
        # instead, and the counter makes a source whose alerts all fell back visible.
        logger.exception("alerts_platform.describer_failed", source=source.value)
        safe_record(increment_describer_failures, source.value)
        return SourceDescription()
    data_link = description.data_link
    if data_link is not None and len(data_link.url) > MAX_DATA_LINK_URL_CHARS:
        logger.warning("alerts_platform.data_link_too_long", source=source.value, length=len(data_link.url))
        data_link = None
    return SourceDescription(
        details=description.details,
        context=tuple(clip_text(line, MAX_CONTEXT_LINE_CHARS) for line in description.context[:MAX_CONTEXT_LINES]),
        data_link=data_link,
    )
