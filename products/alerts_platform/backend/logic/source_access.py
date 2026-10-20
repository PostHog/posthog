"""Which product's access an alert's data falls under.

An alert shows its source product's data: its filters, its firing state, and the values a
transition carries. So reading an alert, or subscribing a workflow to one, also needs read access
to that product. `alert:read` alone must not reveal it.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Final
from uuid import UUID

from posthog.scopes import APIScopeObject, scopes_not_covered

from products.alerts_platform.backend.facade.enums import PlatformAlertConfigurationSourceKind
from products.alerts_platform.backend.models import PlatformAlertConfiguration

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

SOURCE_KIND_RESOURCE: Final[dict[str, APIScopeObject]] = {
    PlatformAlertConfigurationSourceKind.LOGS.value: "logs",
}

# Kinds the read API does not serve. An insight copy shows its insight's bound and firing state,
# and a reader can hold access to insights in general but not to that insight. This product
# cannot check access to one insight, so the copies stay out of the API until it can.
UNSERVED_SOURCE_KINDS: Final[frozenset[str]] = frozenset({PlatformAlertConfigurationSourceKind.INSIGHT.value})


def workflow_trigger_refusal(
    *,
    team_id: int,
    configuration_ids: Collection[UUID],
    user_access_control: UserAccessControl | None,
    token_scopes: list[str] | None,
) -> str | None:
    """Why the caller may not subscribe a workflow to these alerts' transitions, or None when it may.

    `user_access_control` is None for a caller with no person behind it, and `token_scopes` is
    None for session auth, which carries no scopes.
    """
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
