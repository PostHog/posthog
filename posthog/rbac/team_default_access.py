"""The team's default (member/role-agnostic) access control rules, as one preloaded snapshot.

Anonymous shared-link viewers have no identity to match member or role rules against, so
they resolve against the team's *default* rules only - the same "only default rules apply"
treatment property access control gives `user=None`. Warehouse tables/views are today's
consumer; the snapshot carries every resource's default rules so future consumers don't
need their own loader. With no rules configured the global default for warehouse resources
is `editor`, so public links keep working unless an admin explicitly sets a default of `none`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from posthog.constants import AvailableFeature
from posthog.rbac.user_access_control import (
    RESOURCE_INHERITANCE_MAP,
    access_level_satisfied_for_resource,
    default_access_level,
)
from posthog.scopes import APIScopeObject
from posthog.settings import EE_AVAILABLE

if TYPE_CHECKING:
    from posthog.models import Team
    from posthog.shared_link_user import SharedLinkUser

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@dataclass(frozen=True)
class TeamDefaultAccess:
    """The team's default rules - rows with no member and no role attached - loaded once so
    consumers stay query-free. Keyed (resource, resource_id), resource_id None for
    resource-wide defaults."""

    levels: dict[tuple[str, Optional[str]], str]

    @classmethod
    def load(cls, team: "Team") -> "TeamDefaultAccess":
        # Without the access control feature no rules apply - resolution falls through to the
        # global default (editor), mirroring UserAccessControl.access_controls_supported.
        if not EE_AVAILABLE or not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            return cls(levels={})

        rows = AccessControl.objects.filter(
            team=team,
            organization_member=None,
            role=None,
        ).values_list("resource", "resource_id", "access_level")
        return cls(levels={(resource, resource_id): level for resource, resource_id, level in rows})

    def is_denied(self, resource: APIScopeObject, object_id: str) -> bool:
        """Object default > resource default > parent resource default > global default (editor)."""
        parent = RESOURCE_INHERITANCE_MAP.get(resource)
        level = (
            self.levels.get((resource, object_id))
            or self.levels.get((resource, None))
            or (self.levels.get((parent, None)) if parent is not None else None)
            or default_access_level(resource)
        )
        return not access_level_satisfied_for_resource(resource, level, "viewer")

    def cache_fingerprint(self) -> list[tuple[str, str, str]]:
        """Canonical rule-state for the query-cache payload. Shared-link visibility is defined
        entirely by these team-global rules, so keying on them partitions shared entries from
        every member's and orphans them the moment an admin changes the defaults - revocation
        propagates through the cache instead of waiting out the TTL. Covers all resources'
        defaults: a non-warehouse rule change over-invalidates, which is rare and fail-safe."""
        return sorted((resource, object_id or "", level) for (resource, object_id), level in self.levels.items())


def for_shared_link_user(user: "SharedLinkUser", team: "Team") -> TeamDefaultAccess:
    """The request's one snapshot: memoized on the principal, which is created once per request
    and flows to every consumer - each tile's runner, each database build, the cache fingerprint."""
    if user.team_default_access is None:
        user.team_default_access = TeamDefaultAccess.load(team)
    return user.team_default_access
