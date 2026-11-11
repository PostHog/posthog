"""How each source words its own notifications.

The platform imports no source, so a source registers its describer here when Django starts, the
way `products.alerts` registers its destination resolver.
"""

from typing import Final

import structlog

from posthog.slack.channels import clip_text

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    MessageImage,
    SourceDescriber,
    SourceDescription,
    SourceImageResolver,
    SourceKind,
    SourceSlackRenderer,
)

# A source's context names things a user chose, such as services, so its size is unbounded. The
# bound is set once here, so every transport's own budget starts from the same small print.
MAX_CONTEXT_LINES: Final = 3
MAX_CONTEXT_LINE_CHARS: Final = 300
# A data link can carry a whole filter in its query string. Slack refuses a post whose button URL is
# over 3000 characters, so a longer link is dropped rather than costing the message.
MAX_DATA_LINK_URL_CHARS: Final = 2000
# Slack refuses an image block whose URL is over 3000 characters, so a longer image is dropped too.
# Its alt text has a 2000-character limit, which a clip keeps the image inside.
MAX_IMAGE_URL_CHARS: Final = 3000
MAX_IMAGE_ALT_TEXT_CHARS: Final = 2000
MAX_SLACK_ELEMENTS: Final = 3

logger = structlog.get_logger(__name__)

_describers: dict[SourceKind, SourceDescriber] = {}
_image_resolvers: dict[SourceKind, SourceImageResolver] = {}
_slack_renderers: dict[SourceKind, SourceSlackRenderer] = {}


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
        # Bounding the answer is inside the try too, so a describer that returns the wrong shape
        # falls back like one that raises.
        return _bounded(source, describer(project_id=project_id, transition=transition))
    except Exception:
        # The wording is never worth a lost notification. The platform's own wording goes out
        # instead, and the counter makes a source whose alerts all fell back visible.
        logger.exception("alerts_platform.describer_failed", source=source.value)
        # Imported here because source apps reach this module from ready(), and the metrics module
        # would load temporalio into every process at startup.
        from products.alerts_platform.backend.temporal.metrics import (  # noqa: PLC0415 - keeps temporalio off the import path
            increment_describer_failures,
            safe_record,
        )

        safe_record(increment_describer_failures, source.value)
        return SourceDescription()


def _bounded(source: SourceKind, description: SourceDescription) -> SourceDescription:
    data_link = description.data_link
    if data_link is not None and len(data_link.url) > MAX_DATA_LINK_URL_CHARS:
        logger.warning("alerts_platform.data_link_too_long", source=source.value, length=len(data_link.url))
        data_link = None
    return SourceDescription(
        details=description.details,
        context=tuple(clip_text(line, MAX_CONTEXT_LINE_CHARS) for line in description.context[:MAX_CONTEXT_LINES]),
        data_link=data_link,
        # The buttons share the actions block, which Slack caps at 25 elements.
        slack_elements=description.slack_elements[:MAX_SLACK_ELEMENTS],
    )


def register_image_resolver(source: SourceKind, resolver: SourceImageResolver) -> None:
    registered = _image_resolvers.get(source)
    if registered is not None and registered is not resolver:
        raise RuntimeError(f"A different image resolver is already registered for {source} alerts.")
    _image_resolvers[source] = resolver


def resolve_image(source: SourceKind, *, team_id: int, transition: AnnouncedTransition) -> MessageImage | None:
    """The source's picture for a transition, or None. A picture is never worth a lost notification,
    so a resolver that fails sends the message without one."""
    resolver = _image_resolvers.get(source)
    if resolver is None:
        return None
    try:
        image = resolver(team_id=team_id, transition=transition)
    except Exception:
        logger.exception("alerts_platform.image_resolver_failed", source=source.value)
        return None
    if image is None:
        return None
    if len(image.url) > MAX_IMAGE_URL_CHARS:
        logger.warning("alerts_platform.image_url_too_long", source=source.value, length=len(image.url))
        return None
    return MessageImage(url=image.url, alt_text=clip_text(image.alt_text, MAX_IMAGE_ALT_TEXT_CHARS))


def register_slack_renderer(source: SourceKind, renderer: SourceSlackRenderer) -> None:
    registered = _slack_renderers.get(source)
    if registered is not None and registered is not renderer:
        raise RuntimeError(f"A different Slack renderer is already registered for {source} alerts.")
    _slack_renderers[source] = renderer


def slack_renderer_for(source: SourceKind) -> SourceSlackRenderer | None:
    return _slack_renderers.get(source)
