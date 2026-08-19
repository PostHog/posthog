from functools import cached_property
from typing import Any, Optional, cast

from django.db.models import Model, Q

from posthog.models import OrganizationMembership, Team, User
from posthog.rbac.user_access_control import (
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    ResolvedAccess,
    UserAccessControl,
    _AccessControl,
    model_to_resource,
)


class SubjectAccessControl(UserAccessControl):
    """Resolves access for a subject rather than for the requesting user.

    The subject decides which rules count:
    - no subject: only the default rules (scoped to no member and no role) — what applies to everyone
    - member=...: the default rules, the member's own rules, and the rules of the member's roles
    - role_id=...: the default rules and that role's rules

    A member subject keeps the org-admin bypass when their membership level grants it; the
    other subjects never have it.

    For attribution and display (what does or would this subject have) — never for enforcing
    the requesting user's access, which is UserAccessControl's job. `user`/`team` are still the
    requesting user's context; the subject only changes whose rules resolve.
    """

    def __init__(
        self,
        user: User,
        team: Optional[Team] = None,
        organization_id: Optional[str] = None,
        *,
        member: Optional[OrganizationMembership] = None,
        role_id: Optional[str] = None,
    ):
        super().__init__(user, team, organization_id)
        self._subject_member = member
        self._subject_role_id = role_id

    def inherited_access_for_object(self, obj: Model) -> Optional[ResolvedAccess]:
        """The access the subject would have if their override on this object were removed — the
        inherited level the UI shows next to "No override".

        Runs the subject's precheck (a member keeps their creator and org-admin bypasses even
        without the override) and then the same object walk, over the subject's rules with the
        subject's own rows on this object left out — so the answer cannot disagree with how
        access would actually be enforced.

        None when nothing sits above the object (the resources without resource-level
        controls, e.g. a project) — that None is load-bearing for the UI, which must not
        offer "No override" there.
        """
        resource = model_to_resource(obj)
        if not resource or resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS:
            return None

        member = self._subject_member
        is_creator = member is not None and getattr(obj, "created_by", None) == member.user
        resolved, access = self._object_access_level_precheck(resource, is_creator)
        if resolved:
            return access

        rows = [
            ac
            for ac in self._get_access_controls(self._access_controls_filters_for_object(resource, str(obj.id)))  # type: ignore
            if not self._is_subject_row(ac)
        ]
        return self._object_access_level_from_rows(
            resource, rows, fallback_parent_id=self._fallback_parent_id(obj, resource)
        )

    def _is_subject_row(self, access_control: _AccessControl) -> bool:
        """Whether this row is the subject's own — the kind of rule "No override" would remove."""
        if self._subject_member is not None:
            return access_control.organization_member_id == self._subject_member.id
        if self._subject_role_id is not None:
            return str(access_control.role_id) == str(self._subject_role_id)
        return access_control.organization_member_id is None and access_control.role_id is None

    @cached_property
    def _user_role_ids(self):
        if self._subject_member is not None:
            if not self.rbac_supported:
                return []
            return list(
                cast(Any, self._subject_member.user)
                .role_memberships.filter(role__organization_id=self._organization_id)
                .values_list("role_id", flat=True)
            )
        return [self._subject_role_id] if self._subject_role_id else []

    def _filter_options(self, filters: dict[str, Any]) -> Q:
        q = Q(**filters, organization_member=None, role=None)
        if self._subject_member is not None:
            q |= Q(**filters, organization_member=self._subject_member, role=None)
        if self._user_role_ids:
            q |= Q(**filters, organization_member=None, role__in=self._user_role_ids)
        return q

    @property
    def is_organization_admin(self) -> bool:
        return bool(self._subject_member and self._subject_member.level >= OrganizationMembership.Level.ADMIN)
