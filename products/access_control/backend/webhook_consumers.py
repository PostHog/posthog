"""Access Control's GitHub team and membership webhook consumer."""

from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen
from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

_TEAM_ACTIONS = frozenset({"created", "edited", "deleted"})
_MEMBERSHIP_ACTIONS = frozenset({"added", "removed"})


@frozen
class _ParsedTeamDelivery:
    installation_id: str
    action: str
    github_org_login: str
    github_team_id: int
    github_team_slug: str
    github_team_name: str


def _parse_team_delivery(delivery: WebhookDelivery) -> _ParsedTeamDelivery | None:
    payload = delivery.payload
    action = payload.get("action")
    if not isinstance(action, str):
        return None
    if delivery.event_type == "team":
        if action not in _TEAM_ACTIONS:
            return None
    elif delivery.event_type == "membership":
        if action not in _MEMBERSHIP_ACTIONS or payload.get("scope") != "team":
            return None
    else:
        return None

    installation = payload.get("installation")
    raw_installation_id = installation.get("id") if isinstance(installation, Mapping) else None
    if raw_installation_id is None or isinstance(raw_installation_id, bool):
        return None

    organization = payload.get("organization")
    org_login = organization.get("login") if isinstance(organization, Mapping) else None
    if not isinstance(org_login, str) or not org_login.strip():
        return None

    team: Any = payload.get("team")
    if not isinstance(team, Mapping):
        return None
    team_id = team.get("id")
    slug = team.get("slug")
    name = team.get("name")
    if not isinstance(team_id, int) or isinstance(team_id, bool):
        return None
    if not isinstance(slug, str) or not slug.strip():
        return None
    team_name = name.strip() if isinstance(name, str) and name.strip() else slug.strip()

    return _ParsedTeamDelivery(
        installation_id=str(raw_installation_id),
        action=action,
        github_org_login=org_login.strip(),
        github_team_id=team_id,
        github_team_slug=slug.strip(),
        github_team_name=team_name,
    )


def _handle_github_team_event(delivery: WebhookDelivery) -> None:
    parsed = _parse_team_delivery(delivery)
    if parsed is None:
        return
    from products.access_control.backend.facade.api import (  # noqa: PLC0415 - keeps model imports off registry load
        enqueue_github_team_role_webhook,
    )

    enqueue_github_team_role_webhook(
        installation_id=parsed.installation_id,
        action=parsed.action,
        github_org_login=parsed.github_org_login,
        github_team_id=parsed.github_team_id,
        github_team_slug=parsed.github_team_slug,
        github_team_name=parsed.github_team_name,
    )


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="access_control_github_team_roles",
        provider="github",
        app="posthog",
        event_types=frozenset({"team", "membership"}),
        handler=_handle_github_team_event,
    ),
)
