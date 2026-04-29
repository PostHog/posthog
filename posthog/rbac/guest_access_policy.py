"""Guest-aware decisions in one place.

Whenever the access-control or permissions layer notices that the requesting
user is a guest (`OrganizationMembership.is_guest=True`), it delegates to one of
the named functions here. Adding a new guest concern means adding a function in
this module — with its own docstring and unit test — instead of dropping a
conditional somewhere in the AC plumbing.

This keeps the AC layer thin and makes guest behavior reviewable in a single
file. It also gives us a stable seam to extend (e.g. for editor guests beyond
viewer, or for guest-only audit redaction) without touching the rest of the
permission stack.
"""

from typing import Any, Optional

from posthog.models import OrganizationMembership
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.scopes import APIScopeObject

# Resources a guest can be granted explicit access to via an `AccessControl` row.
# Anything not in this set is implicitly denied for guests.
GUEST_GRANTABLE_RESOURCES: frozenset[APIScopeObject] = frozenset({"dashboard", "insight", "notebook"})

# Frame-level resources without per-row AC entries — guests must still be allowed
# the project shell so their granted dashboards/insights can render. The
# deny-by-default for guests applies on the per-object resources beneath, never on
# the frame itself. Note: "organization" is handled by an earlier branch in the AC
# layer (returns admin/member based on level for any user) so it doesn't need to
# appear here. "plugin" is intentionally excluded — guests don't access plugin
# endpoints today and we don't want to widen the surface preemptively.
GUEST_FRAME_LEVEL_RESOURCES: frozenset[APIScopeObject] = frozenset({"project"})

# Team-payload fields the standard serializer exposes that a guest doesn't need
# (write key, onboarding signals). Stripped by `filter_and_sanitize_teams_for_guest_access`.
GUEST_REDACTED_TEAM_FIELDS: frozenset[str] = frozenset(
    {
        "api_token",
        "completed_snippet_onboarding",
        "has_completed_onboarding_for",
        "ingested_event",
    }
)


def guest_object_access_level(resource: APIScopeObject, *, explicit: bool) -> Optional[Any]:
    """Return what `UserAccessControl.access_level_for_object` should return for a guest
    in the absence of a specific AC row.

    Frame-level resources (currently just "project") fall through to the regular default
    so the project shell renders for the granted dashboard/insight/notebook scenes.
    Per-object resources (dashboard/insight/notebook/etc.) get NO_ACCESS_LEVEL so the
    guest's deny-by-default fires correctly. The caller is responsible for not invoking
    this for "organization" — that resource has its own admin/member branch upstream.
    """
    from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, default_access_level

    if resource in GUEST_FRAME_LEVEL_RESOURCES:
        return default_access_level(resource) if not explicit else None
    return NO_ACCESS_LEVEL if not explicit else None


def guest_resource_access_level(resource: APIScopeObject) -> Any:
    """Return what `UserAccessControl.access_level_for_resource` should return for a guest
    in the absence of any specific AC row.

    Always NO_ACCESS_LEVEL: a guest has no resource-level fallback. Their access is
    expressed solely via per-object AC rows; the resource-level default is "deny."
    Frame-level resources are short-circuited by the AC layer earlier (for all users)
    so they never reach this path.
    """
    from posthog.rbac.user_access_control import NO_ACCESS_LEVEL

    return NO_ACCESS_LEVEL


def guest_effective_team_membership_level(
    membership: OrganizationMembership, team_id: int
) -> Optional[OrganizationMembership.Level]:
    """Return what `UserTeamPermissions.effective_membership_level` should return for a guest.

    A guest is "a member" of a team iff they hold any per-object AC row on it. Without
    this, `TeamMemberAccessPermission` would 403 every project endpoint for guests
    because they never have project-resource AC rows directly.

    The lookup is direct (not via the prefetched cache used for regular members) because
    the cache only contains `resource="project"` rows — guests have rows on dashboards,
    insights, notebooks instead.
    """
    from ee.models.rbac.access_control import AccessControl

    has_grant = AccessControl.objects.filter(
        team_id=team_id,
        organization_member=membership,
        resource__in=GUEST_GRANTABLE_RESOURCES,
    ).exists()
    return OrganizationMembership.Level.MEMBER if has_grant else None


def filter_and_sanitize_teams_for_guest_access(
    organization: Organization,
    user: Optional[User],
    teams_data: list[dict[str, Any]],
    request: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Strip guest-irrelevant fields from a serialized team payload when the requester is a guest.

    The team-level access filter (which teams a guest sees) is handled upstream by the
    AC layer + `team_ids_visible_for_user`. This function only sanitizes the *fields* of
    each visible team so that admin-only metadata (write keys, onboarding flags) doesn't
    leak into the guest-facing payload. Returns the input unchanged for non-guests.

    When a `request` is provided, defers to the request-scoped guest cache so that the
    same is_guest check shared across the middleware and `UserSerializer` is reused
    rather than firing a separate `OrganizationMembership` lookup per call.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return teams_data

    if request is not None:
        from posthog.rbac.guest_request_cache import is_user_guest_in_org

        if not is_user_guest_in_org(request, organization.id):
            return teams_data
    else:
        membership = OrganizationMembership.objects.filter(organization=organization, user=user).first()
        if not membership or not membership.is_guest:
            return teams_data

    return [{k: v for k, v in team.items() if k not in GUEST_REDACTED_TEAM_FIELDS} for team in teams_data]


# Fields a serialized user dict (`UserBasicSerializer` output and similar) carries
# that a guest doesn't need and that the surface pass found leaking team-member PII
# through embedded `created_by` / `last_modified_by` payloads — e.g. on notebooks.
# Strip these to display-name fragments only when the requester is a guest.
GUEST_REDACTED_USER_FIELDS: frozenset[str] = frozenset(
    {
        "email",
        "uuid",
        "distinct_id",
        "role",
        "role_at_organization",
        "id",
        "is_email_verified",
        "is_2fa_enabled",
        "has_password",
    }
)


def redact_user_for_guest(
    payload: Optional[dict[str, Any]],
    request: Optional[Any],
) -> Optional[dict[str, Any]]:
    """Return a copy of a serialized user dict with PII fields stripped when the
    requester is a guest. Returns the input unchanged for non-guests / when there is
    no request context (defensive: guest deflection only applies inside a request).

    Centralizes the redaction so callers (notebook serializer, future activity-log
    surfaces, etc.) can drop in a one-line wrap around their nested user serializer
    output without re-deriving guest status.
    """
    if not isinstance(payload, dict):
        return payload
    if request is None:
        return payload
    from posthog.rbac.guest_request_cache import is_user_guest_in_any_org

    if not is_user_guest_in_any_org(request):
        return payload
    return {k: v for k, v in payload.items() if k not in GUEST_REDACTED_USER_FIELDS}


def redact_team_for_guest(
    payload: Optional[dict[str, Any]],
    request: Optional[Any],
) -> Optional[dict[str, Any]]:
    """Return a copy of a serialized team dict with admin-only metadata stripped when
    the requester is a guest in the team's organization. Mirrors
    `filter_and_sanitize_teams_for_guest_access` for single-team payloads emitted
    outside the `OrganizationSerializer.get_teams` path — most importantly the
    `team` field on `UserSerializer`, which goes through `TeamBasicSerializer`
    directly and would otherwise leak `api_token` and onboarding flags to guests.

    The is_guest check is scoped to the team's specific organization (read from the
    payload) so a user who is a guest in org A but a regular member of org B sees
    full team data when their current team is in B. Returns the input unchanged for
    non-guests, anonymous requests, payloads missing an `organization` field, or
    when there is no request context.
    """
    if not isinstance(payload, dict):
        return payload
    if request is None:
        return payload
    organization_id = payload.get("organization")
    if organization_id is None:
        return payload
    from posthog.rbac.guest_request_cache import is_user_guest_in_org

    if not is_user_guest_in_org(request, organization_id):
        return payload
    return {k: v for k, v in payload.items() if k not in GUEST_REDACTED_TEAM_FIELDS}


def redact_user_fields_for_guest(
    data: dict[str, Any],
    fields: tuple[str, ...] | list[str],
    request: Optional[Any],
) -> None:
    """Mutate `data` in-place, stripping PII fields from each nested user-serializer
    payload listed in `fields` when the requester is a guest. No-op for non-guests so
    the hot path stays cheap.

    Intended as a single call site replacing per-field `redact_user_for_guest` wrapping;
    the `GuestRedactedUserFieldsMixin` below is the declarative form for serializers that
    embed nested user payloads.
    """
    if request is None or not fields:
        return
    from posthog.rbac.guest_request_cache import is_user_guest_in_any_org

    if not is_user_guest_in_any_org(request):
        return
    for field in fields:
        payload = data.get(field)
        if isinstance(payload, dict):
            data[field] = {k: v for k, v in payload.items() if k not in GUEST_REDACTED_USER_FIELDS}


class GuestRedactedUserFieldsMixin:
    """Serializer mixin that redacts PII (email, uuid, distinct_id, role, ...) from
    nested user-serializer payloads when the requester is a guest.

    Declare which fields hold serialized users in `guest_redacted_user_fields`:

        class NotebookMinimalSerializer(
            GuestRedactedUserFieldsMixin,
            serializers.ModelSerializer,
            UserAccessControlSerializerMixin,
        ):
            guest_redacted_user_fields = ("created_by", "last_modified_by")

    Place this mixin BEFORE `serializers.ModelSerializer` in the MRO so its
    `to_representation` runs after the base implementation has already produced the
    serialized dict.
    """

    guest_redacted_user_fields: tuple[str, ...] = ()

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)  # type: ignore[misc]
        if self.guest_redacted_user_fields and isinstance(data, dict):
            redact_user_fields_for_guest(data, self.guest_redacted_user_fields, self.context.get("request"))  # type: ignore[attr-defined]
        return data
