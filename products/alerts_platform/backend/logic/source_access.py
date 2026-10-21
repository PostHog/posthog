"""Which product's access an alert's data falls under.

An alert shows its source product's data: its filters, its firing state, and the values a
transition carries. So reading an alert, or subscribing a workflow to one, also needs read access
to that product. `alert:read` alone must not reveal it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.scopes import scopes_not_covered

from products.alerts_platform.backend.facade.contracts import SOURCE_KIND_RESOURCE
from products.alerts_platform.backend.facade.enums import PlatformAlertConfigurationSourceKind
from products.alerts_platform.backend.models import PlatformAlertConfiguration

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def trigger_configuration_ids(filters: Mapping[str, object]) -> list[UUID] | None:
    """The alerts an `$alert_transition` trigger's filters name, or None when a named one is not an alert id."""
    ids: list[UUID] = []
    properties = filters.get("properties")
    for prop in properties if isinstance(properties, list) else []:
        if not isinstance(prop, dict) or prop.get("key") != "alert_configuration_id":
            continue
        # Only an exact event-property filter restricts which events match. Another type, such
        # as a flag, compiles to a condition that does not read the event at all.
        if prop.get("type") != "event" or (prop.get("operator") or "exact") != "exact":
            continue
        value = prop.get("value")
        for item in value if isinstance(value, list) else [value]:
            try:
                ids.append(UUID(str(item)))
            except ValueError:
                return None
    return ids


def workflow_trigger_refusal(
    *,
    team_id: int,
    filters: Mapping[str, object],
    user_access_control: UserAccessControl | None,
    token_scopes: list[str] | None,
    allow_no_alerts: bool = False,
) -> str | None:
    """Why the caller may not subscribe a workflow to the alerts these trigger filters name, or None.

    `user_access_control` is None for a caller with no person behind it, and `token_scopes` is
    None for session auth, which carries no scopes.
    """
    configuration_ids = trigger_configuration_ids(filters)
    if configuration_ids is None:
        return "Pick alerts from the list for this trigger."
    if not configuration_ids:
        return (
            None
            if allow_no_alerts
            else "Pick an alert for this trigger. Without one it runs for every alert in the project."
        )
    kinds = dict(
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(id__in=configuration_ids)
        .values_list("id", "source_kind")
    )
    if len(kinds) != len(set(configuration_ids)):
        return "One of these alerts does not exist in this project."
    for source_kind in sorted(set(kinds.values())):
        resource = SOURCE_KIND_RESOURCE.get(source_kind)
        if resource is None:
            return f"A workflow cannot be triggered by {PlatformAlertConfigurationSourceKind(source_kind).label} alerts yet."
        if user_access_control is not None and not user_access_control.check_access_level_for_resource(
            resource, "viewer"
        ):
            return f"You need access to {resource} to trigger a workflow from these alerts."
        if (
            token_scopes is not None
            and "*" not in token_scopes
            and scopes_not_covered(token_scopes, [f"{resource}:read"])
        ):
            return f"This API key needs the {resource}:read scope to trigger a workflow from these alerts."
    return None
