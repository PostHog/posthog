from collections import defaultdict
from collections.abc import Mapping, Sequence

from django.db import transaction

from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.models.activity_logging.personal_api_key_utils import OrganizationAdminKeyActionContext
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


class KeyActionOutcome(LabeledStrEnum):
    ROLLED = "rolled"
    DELETED = "deleted"
    ACCESS_REMOVED = "access_removed"


@frozen
class KeyActionResult:
    outcome: KeyActionOutcome
    owner_id: int
    label: str
    mask_value: str


@frozen
class _KeyScopes:
    scoped_teams: list[int] | None
    scoped_organizations: list[str] | None


class OrganizationPersonalAPIKeyActions:
    """Roll and revoke, by an admin of `organization`, of personal API keys that reach it.

    Each action locks the key and computes its reach again. An action returns `None` when the
    locked key no longer reaches the organization.
    """

    def __init__(self, organization: Organization, acting_user: User) -> None:
        self._organization_id = str(organization.id)
        self._acting_user = acting_user

    def roll(self, key_id: str) -> KeyActionResult | None:
        with transaction.atomic():
            key = self._lock(key_id)
            if key is None:
                return None
            if not KeyReachResolver.for_keys([key]).reach(key, self._organization_id).reaches_organization:
                return None
            result = self._result(key, KeyActionOutcome.ROLLED)
            with ActingUserContext(self._acting_user), OrganizationAdminKeyActionContext(self._organization_id):
                PersonalAPIKeySerializer(instance=key).roll(key)
            return result

    def revoke(self, key_id: str) -> KeyActionResult | None:
        with transaction.atomic():
            key = self._lock(key_id)
            if key is None:
                return None
            resolver = KeyReachResolver.for_keys([key])
            reach = resolver.reach(key, self._organization_id)
            if not reach.reaches_organization:
                return None
            scopes = self._scopes_without_organization(key, reach, resolver.team_organization_ids)
            with ActingUserContext(self._acting_user), OrganizationAdminKeyActionContext(self._organization_id):
                if scopes is None:
                    result = self._result(key, KeyActionOutcome.DELETED)
                    key.delete()
                else:
                    result = self._result(key, KeyActionOutcome.ACCESS_REMOVED)
                    key.scoped_teams = scopes.scoped_teams
                    key.scoped_organizations = scopes.scoped_organizations
                    key.save(update_fields=["scoped_teams", "scoped_organizations"])
            return result

    @staticmethod
    def _lock(key_id: str) -> PersonalAPIKey | None:
        # `of=("self",)` locks only the key row, not the owner's user row that `select_related` joins.
        return PersonalAPIKey.objects.select_for_update(of=("self",)).select_related("user").filter(pk=key_id).first()

    @staticmethod
    def _result(key: PersonalAPIKey, outcome: KeyActionOutcome) -> KeyActionResult:
        return KeyActionResult(outcome=outcome, owner_id=key.user_id, label=key.label, mask_value=key.mask_value or "")

    def _scopes_without_organization(
        self, key: PersonalAPIKey, reach: KeyReach, team_organization_ids: Mapping[int, str]
    ) -> _KeyScopes | None:
        """The key's scopes without this organization, or `None` when the key must be deleted instead.

        An empty or null list removes that limit, and a key with both lists empty has full access. So a
        change that would empty a list that held entries deletes the key instead. Entries for
        organizations the owner left and for deleted teams stay, because they grant nothing.
        """
        if not reach.other_organization_ids:
            return None
        teams, orgs = key.scoped_teams or [], key.scoped_organizations or []
        if not teams and not orgs:
            return _KeyScopes(scoped_teams=key.scoped_teams, scoped_organizations=sorted(reach.other_organization_ids))
        new_teams = [team_id for team_id in teams if team_organization_ids.get(team_id) != self._organization_id]
        new_orgs = [organization_id for organization_id in orgs if organization_id != self._organization_id]
        if (teams and not new_teams) or (orgs and not new_orgs):
            return None
        return _KeyScopes(
            scoped_teams=new_teams if teams else key.scoped_teams,
            scoped_organizations=new_orgs if orgs else key.scoped_organizations,
        )
