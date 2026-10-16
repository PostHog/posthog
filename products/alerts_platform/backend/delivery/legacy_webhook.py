"""The webhook body a source's own stack sent, for the teams still allowed to receive it.

A source registers its body when Django starts, the way it registers its describer. Teams that
had webhook destinations before the platform delivered for them keep that body until a set date,
so a receiver that parses it does not break when the platform takes over.
"""

from typing import Final

from products.alerts_platform.backend.facade.contracts import LegacyWebhookBody, SourceKind

# A closed list of teams. No team joins it after the platform delivers for its source.
LEGACY_WEBHOOK_BODY_FLAG: Final = "alert-platform-legacy-webhook-body"

# The header value the HogFunction path sends with its body.
LEGACY_WEBHOOK_VERSION: Final = "1"

_bodies: dict[SourceKind, LegacyWebhookBody] = {}


def register(source: SourceKind, body: LegacyWebhookBody) -> None:
    registered = _bodies.get(source)
    if registered is not None and registered is not body:
        raise RuntimeError(f"A different legacy webhook body is already registered for {source} alerts.")
    _bodies[source] = body


def body_for(source: SourceKind) -> LegacyWebhookBody | None:
    return _bodies.get(source)
