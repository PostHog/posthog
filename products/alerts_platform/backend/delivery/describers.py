"""How each source words its own notifications.

The platform imports no source, so a source registers its describer here when Django starts, the
way `products.alerts` registers its destination resolver.
"""

import structlog

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    SourceDescriber,
    SourceDescription,
    SourceKind,
)

logger = structlog.get_logger(__name__)

_describers: dict[SourceKind, SourceDescriber] = {}


def register(source: SourceKind, describer: SourceDescriber) -> None:
    # One owner per source. A second registrant would silently reword another product's alerts.
    registered = _describers.get(source)
    if registered is not None and registered is not describer:
        raise RuntimeError(f"A different describer is already registered for {source} alerts.")
    _describers[source] = describer


def describe(source: SourceKind, *, project_id: int, transition: AnnouncedTransition) -> SourceDescription | None:
    """The source's own words for a transition, or None when the platform's wording must do.

    None rather than an error when nothing is registered: the platform's wording is a complete
    message, so a source without a describer still delivers.
    """
    describer = _describers.get(source)
    if describer is None:
        return None
    try:
        return describer(project_id=project_id, transition=transition)
    except Exception:
        # The wording is never worth a lost notification. The platform's own wording goes out
        # instead, and the error is logged for the source to fix.
        logger.exception("alerts_platform.describer_failed", source=source.value)
        return None
