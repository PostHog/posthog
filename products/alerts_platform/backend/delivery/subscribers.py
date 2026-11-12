"""The people an email or in-app destination names by user id, resolved when a delivery sends.

A stored address keeps sending after its user changes it, loses access, or leaves the organization.
A user id is resolved at each send instead: to the user's current address, and only while the user
can view the alert's project and passes the source's own access rule. The platform imports no
source, so a source registers that rule here when Django starts. A source with no rule reaches
nobody this way, because the platform cannot tell who may see what its alerts are about.
"""

from typing import cast
from uuid import UUID

from posthog.models import Team, User

from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    DestinationType,
    SourceKind,
    SubscriberAccess,
)

_access: dict[SourceKind, SubscriberAccess] = {}


def register(source: SourceKind, access: SubscriberAccess) -> None:
    # One owner per source. A second registrant would silently replace who may hear about its alerts.
    registered = _access.get(source)
    if registered is not None and registered is not access:
        raise RuntimeError(f"A different subscriber access rule is already registered for {source} alerts.")
    _access[source] = access


def resolve(
    source: SourceKind, *, team: Team, configuration_id: UUID, data: AlertDestinationData
) -> AlertDestinationData | None:
    """The destination with its users resolved, or None when none of them may hear about the alert.

    A destination that names no user, such as one with stored addresses, is returned as it is.
    """
    if data["type"] == DestinationType.EMAIL and "email_user_ids" in data:
        users = _users_with_access(
            source, team=team, configuration_id=configuration_id, user_ids=data["email_user_ids"]
        )
        # Sorted and deduplicated, because delivery tells destinations apart by their data.
        addresses = sorted({email for _, email in users if email})
        if not addresses:
            return None
        resolved = cast(AlertDestinationData, {k: v for k, v in data.items() if k != "email_user_ids"})
        resolved["email_addresses"] = addresses
        return resolved
    if data["type"] == DestinationType.IN_APP:
        users = _users_with_access(
            source, team=team, configuration_id=configuration_id, user_ids=data.get("in_app_user_ids", [])
        )
        if not users:
            return None
        return {**data, "in_app_user_ids": sorted(user_id for user_id, _ in users)}
    return data


def _users_with_access(
    source: SourceKind, *, team: Team, configuration_id: UUID, user_ids: list[int]
) -> list[tuple[int, str]]:
    access = _access.get(source)
    if access is None or not user_ids:
        return []
    # By uuid, so the project's member and role rules are evaluated for these users only.
    uuids = [str(uuid) for uuid in User.objects.filter(id__in=user_ids).values_list("uuid", flat=True)]
    candidates = list(team.all_users_with_access(user_uuids=uuids).values_list("id", "email"))
    if not candidates:
        return []
    allowed = set(access(team_id=team.id, configuration_id=configuration_id, user_ids=[uid for uid, _ in candidates]))
    return [(user_id, email) for user_id, email in candidates if user_id in allowed]
