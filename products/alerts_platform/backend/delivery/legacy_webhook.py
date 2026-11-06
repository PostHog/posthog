"""The webhook body a source's own stack sent, for the teams still allowed to receive it.

A source registers its body when Django starts, the way it registers its describer. Teams that
had webhook destinations before the platform delivered for them keep that body until a set date,
so a receiver that parses it does not break when the platform takes over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.facade.contracts import LegacyWebhookBody, SourceKind

if TYPE_CHECKING:
    from posthog.models import Team

# A closed list of teams. No team joins it after the platform delivers for its source.
LEGACY_WEBHOOK_BODY_FLAG: Final = "alert-platform-legacy-webhook-body"

# While this is off for a team, it keeps the legacy body even when it is not on the list above.
# The list is topped up right before this turns on, so a team that added its first webhook in
# between does not switch bodies under a receiver that already parses the legacy one.
ALERTMANAGER_WEBHOOK_BODY_FLAG: Final = "alert-platform-alertmanager-webhook-body"

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


def keeps_legacy_webhook_body(team: Team) -> bool | None:
    """Whether native delivery sends this team the body its source's own stack sent. None when unknown."""
    listed = team_flag_enabled(LEGACY_WEBHOOK_BODY_FLAG, team)
    if listed is None or listed:
        return listed
    gets_alertmanager_body = team_flag_enabled(ALERTMANAGER_WEBHOOK_BODY_FLAG, team)
    return None if gets_alertmanager_body is None else not gets_alertmanager_body
