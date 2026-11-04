from collections import defaultdict
from collections.abc import Mapping, Sequence

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team
from posthog.models.personal_api_key import PersonalAPIKey


@frozen
class KeyReach:
    reaches_organization: bool
    other_organization_ids: frozenset[str]


class KeyReachResolver:
    """Reach follows `posthog/permissions.py`, which applies each non-empty `scoped_teams` and
    `scoped_organizations` list as its own limit. An organization the owner left never counts."""

    def __init__(
        self, *, member_organization_ids: Mapping[int, frozenset[str]], team_organization_ids: Mapping[int, str]
    ) -> None:
        self._member_organization_ids = member_organization_ids
        self.team_organization_ids = team_organization_ids

    @classmethod
    def for_keys(cls, keys: Sequence[PersonalAPIKey]) -> "KeyReachResolver":
        owner_ids = {key.user_id for key in keys}
        scoped_team_ids = {team_id for key in keys for team_id in key.scoped_teams or []}

        member_organization_ids: defaultdict[int, set[str]] = defaultdict(set)
        for user_id, organization_id in OrganizationMembership.objects.filter(user_id__in=owner_ids).values_list(
            "user_id", "organization_id"
        ):
            member_organization_ids[user_id].add(str(organization_id))

        team_organization_ids = {
            team_id: str(organization_id)
            for team_id, organization_id in Team.objects.filter(id__in=scoped_team_ids).values_list(
                "id", "organization_id"
            )
        }

        return cls(
            member_organization_ids={
                user_id: frozenset(organization_ids) for user_id, organization_ids in member_organization_ids.items()
            },
            team_organization_ids=team_organization_ids,
        )

    def reach(self, key: PersonalAPIKey, organization_id: str) -> KeyReach:
        live = self._member_organization_ids.get(key.user_id, frozenset())
        team_org = self.team_organization_ids
        teams, orgs = key.scoped_teams or [], key.scoped_organizations or []
        if teams:
            reachable = {
                team_org[t]
                for t in teams
                if t in team_org and team_org[t] in live and (not orgs or team_org[t] in orgs)
            }
        elif orgs:
            reachable = set(orgs) & live
        else:
            reachable = set(live)
        return KeyReach(
            reaches_organization=organization_id in reachable,
            other_organization_ids=frozenset(reachable - {organization_id}),
        )
