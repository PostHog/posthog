from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime
from functools import partial
from itertools import groupby
from operator import attrgetter

from django.db import transaction
from django.utils import timezone

from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.models.activity_logging.personal_api_key_utils import OrganizationAdminKeyActionContext
from posthog.models.personal_api_key import (
    PersonalAPIKey,
    get_organization_ids_in_key_scope,
    get_organization_personal_api_keys,
)
from posthog.tasks.email import send_personal_api_keys_changed_by_org_admin


def load_team_organization_ids(team_ids: Collection[int]) -> dict[int, str]:
    return {
        team_id: str(organization_id)
        for team_id, organization_id in Team.objects.filter(id__in=team_ids).values_list("id", "organization_id")
    }


@frozen
class PersonalAPIKeyOrganizationAccess:
    has_access_to_organization: bool
    other_organization_ids: frozenset[str]


class PersonalAPIKeyOrganizationAccessResolver:
    """A key reaches the organizations that `get_organization_ids_in_key_scope` allows and the owner is a member of.
    An organization the owner left never counts."""

    def __init__(
        self, *, member_organization_ids: Mapping[int, frozenset[str]], team_organization_ids: Mapping[int, str]
    ) -> None:
        self._member_organization_ids = member_organization_ids
        self.team_organization_ids = team_organization_ids

    @classmethod
    def for_keys(cls, keys: Sequence[PersonalAPIKey]) -> "PersonalAPIKeyOrganizationAccessResolver":
        owner_ids = {key.user_id for key in keys}
        scoped_team_ids = {team_id for key in keys for team_id in key.scoped_teams or []}

        member_organization_ids: defaultdict[int, set[str]] = defaultdict(set)
        for user_id, organization_id in OrganizationMembership.objects.filter(user_id__in=owner_ids).values_list(
            "user_id", "organization_id"
        ):
            member_organization_ids[user_id].add(str(organization_id))

        return cls(
            member_organization_ids={
                user_id: frozenset(organization_ids) for user_id, organization_ids in member_organization_ids.items()
            },
            team_organization_ids=load_team_organization_ids(scoped_team_ids),
        )

    def resolve(self, key: PersonalAPIKey, organization_id: str) -> PersonalAPIKeyOrganizationAccess:
        member_organization_ids = self._member_organization_ids.get(key.user_id, frozenset())
        organization_ids_in_scope = get_organization_ids_in_key_scope(key, self.team_organization_ids)
        reachable = (
            member_organization_ids
            if organization_ids_in_scope is None
            else organization_ids_in_scope & member_organization_ids
        )
        return PersonalAPIKeyOrganizationAccess(
            has_access_to_organization=organization_id in reachable,
            other_organization_ids=frozenset(reachable - {organization_id}),
        )


class KeyActionOutcome(LabeledStrEnum):
    ROLLED = "rolled"
    DELETED = "deleted"


@frozen
class KeyActionResult:
    outcome: KeyActionOutcome
    owner_id: int
    label: str
    mask_value: str


@frozen
class BulkKeyActionSummary:
    rolled: int
    deleted: int
    skipped: int
    failed: int
    # A retry passes this back as `skip_rolled_since`, so it is the start of the first attempt.
    started_at: datetime


class OrganizationPersonalAPIKeyActions:
    """Roll and revoke, by an admin of `organization`, of personal API keys that reach it.

    Each action locks the key and checks its organization access again, and leaves alone a key that no longer
    reaches the organization. Each owner gets one email about the keys that one action changed.
    """

    def __init__(self, organization: Organization, acting_user: User) -> None:
        self._organization = organization
        self._organization_id = str(organization.id)
        self._acting_user = acting_user

    @staticmethod
    def _result(key: PersonalAPIKey, outcome: KeyActionOutcome) -> KeyActionResult:
        return KeyActionResult(outcome=outcome, owner_id=key.user_id, label=key.label, mask_value=key.mask_value or "")

    @staticmethod
    def _lock(key_id: str, owner_id: int) -> PersonalAPIKey | None:
        # `of=("self",)` locks only the key row, not the owner's user row that `select_related` joins.
        return (
            PersonalAPIKey.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(pk=key_id, user_id=owner_id)
            .first()
        )

    def _lock_key_reaching_organization(
        self, key_id: str, owner_id: int, team_organization_ids: Mapping[int, str] | None
    ) -> PersonalAPIKey | None:
        key = self._lock(key_id, owner_id)
        if key is None:
            return None
        scoped_team_ids = set(key.scoped_teams or [])
        # A team that the bulk run did not load would make the key look out of reach.
        if team_organization_ids is None or not scoped_team_ids <= team_organization_ids.keys():
            team_organization_ids = load_team_organization_ids(scoped_team_ids)
        organization_ids_in_scope = get_organization_ids_in_key_scope(key, team_organization_ids)
        if organization_ids_in_scope is not None and self._organization_id not in organization_ids_in_scope:
            return None
        # The membership is read after the key lock, so a key whose owner left the organization stays unchanged.
        is_member = OrganizationMembership.objects.filter(user_id=owner_id, organization_id=self._organization.id)
        return key if is_member.exists() else None

    def _roll_locked(self, key: PersonalAPIKey) -> KeyActionResult:
        with ActingUserContext(self._acting_user), OrganizationAdminKeyActionContext(self._organization_id):
            PersonalAPIKeySerializer(instance=key).roll(key)
        # The roll sets a new mask, which is the one the owner sees in their settings.
        return self._result(key, KeyActionOutcome.ROLLED)

    def _revoke_locked(self, key: PersonalAPIKey) -> KeyActionResult:
        result = self._result(key, KeyActionOutcome.DELETED)
        with ActingUserContext(self._acting_user), OrganizationAdminKeyActionContext(self._organization_id):
            key.delete()
        return result

    def _queue_owner_email(self, owner_id: int, results: Sequence[KeyActionResult]) -> None:
        if not results:
            return
        transaction.on_commit(
            partial(
                send_personal_api_keys_changed_by_org_admin.delay,
                user_id=owner_id,
                organization_id=self._organization_id,
                changes=[
                    {"label": result.label, "mask_value": result.mask_value, "outcome": str(result.outcome)}
                    for result in results
                ],
            ),
            robust=True,
        )

    def _act_on_one(
        self, key_id: str, owner_id: int, act: Callable[[PersonalAPIKey], KeyActionResult]
    ) -> KeyActionResult | None:
        with transaction.atomic():
            key = self._lock_key_reaching_organization(key_id, owner_id, team_organization_ids=None)
            if key is None:
                return None
            result = act(key)
            self._queue_owner_email(owner_id, [result])
        return result

    def _act_on_all(
        self, act: Callable[[PersonalAPIKey], KeyActionResult], skip_rolled_since: datetime | None
    ) -> BulkKeyActionSummary:
        started_at = skip_rolled_since or timezone.now()
        # Teams load once for the whole run. The keys are grouped by owner, so that an owner's email goes out when
        # that owner's keys are done, not after the last key.
        keys = list(get_organization_personal_api_keys(self._organization).order_by("user_id", "pk"))
        team_organization_ids = load_team_organization_ids({team for key in keys for team in key.scoped_teams or []})
        outcomes: Counter[KeyActionOutcome] = Counter()
        skipped = failed = 0
        for owner_id, owner_keys in groupby(keys, key=attrgetter("user_id")):
            owner_results: list[KeyActionResult] = []
            for listed_key in owner_keys:
                try:
                    with transaction.atomic():
                        key = self._lock_key_reaching_organization(listed_key.id, owner_id, team_organization_ids)
                        if key is None:
                            continue
                        if skip_rolled_since and key.last_rolled_at and key.last_rolled_at >= skip_rolled_since:
                            skipped += 1
                            continue
                        result = act(key)
                except Exception as error:
                    # A key that fails does not stop the run. The summary counts it, so that the admin can retry.
                    capture_exception(error, {"organization_id": self._organization_id, "key_id": listed_key.id})
                    failed += 1
                    continue
                # Only a committed change counts, so that a failed commit sends no email about the key.
                owner_results.append(result)
            self._queue_owner_email(owner_id, owner_results)
            outcomes.update(result.outcome for result in owner_results)
        return BulkKeyActionSummary(
            rolled=outcomes[KeyActionOutcome.ROLLED],
            deleted=outcomes[KeyActionOutcome.DELETED],
            skipped=skipped,
            failed=failed,
            started_at=started_at,
        )

    def roll(self, key_id: str, owner_id: int) -> KeyActionResult | None:
        return self._act_on_one(key_id, owner_id, self._roll_locked)

    def revoke(self, key_id: str, owner_id: int) -> KeyActionResult | None:
        return self._act_on_one(key_id, owner_id, self._revoke_locked)

    def roll_all(self, skip_rolled_since: datetime | None = None) -> BulkKeyActionSummary:
        """Roll every key that reaches the organization, except keys rolled at or after `skip_rolled_since`."""
        return self._act_on_all(self._roll_locked, skip_rolled_since)

    def revoke_all(self) -> BulkKeyActionSummary:
        return self._act_on_all(self._revoke_locked, skip_rolled_since=None)
