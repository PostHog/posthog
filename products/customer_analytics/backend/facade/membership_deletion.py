from collections.abc import Sequence
from uuid import UUID

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.person.util import PersonTombstone

from products.customer_analytics.backend.logic import membership_deletion
from products.customer_analytics.backend.logic.membership_deletion_receipts import register_membership_deletion_team
from products.customer_analytics.backend.logic.membership_deletion_sources import MembershipDeletionSources


def register_membership_team(team_id: int) -> None:
    register_membership_deletion_team(team_id)


def captures_membership_deletion(team_id: int) -> bool:
    return MembershipDeletionSources.captures_team(team_id)


def create_person_membership_deletion_intents(team_id: int, person_uuids: Sequence[UUID]) -> str | None:
    return MembershipDeletionSources.create_person_intents(team_id, person_uuids)


def record_person_membership_deletion_tombstones(
    team_id: int,
    tombstones: Sequence[PersonTombstone],
    *,
    source_key: str | None = None,
    required: bool = False,
) -> None:
    MembershipDeletionSources.record_tombstones(team_id, tombstones, source_key=source_key, required=required)


def capture_person_membership_before_purge(team_id: int, person_uuids: Sequence[str]) -> None:
    MembershipDeletionSources.capture_before_purge(team_id, person_uuids)


def tombstone_persons_with_membership_receipts(team_id: int, person_ids: Sequence[int], source_key: str) -> int:
    return MembershipDeletionSources.tombstone_persons(team_id, person_ids, source_key)


def record_team_membership_deletion(team_ids: Sequence[int]) -> None:
    MembershipDeletionSources.record_team_deletion(team_ids)


def create_team_persons_membership_deletion_intent(team_id: int, source_key: str) -> UUID | None:
    return MembershipDeletionSources.create_team_persons_intent(team_id, source_key)


def confirm_team_persons_membership_purge(team_id: int, receipt_id: UUID | None, *, exhausted: bool) -> None:
    MembershipDeletionSources.confirm_team_persons_purge(team_id, receipt_id, exhausted=exhausted)


def delete_team_membership(cluster: ClickhouseCluster, team_ids: Sequence[int], *, include_config: bool = True) -> None:
    membership_deletion.delete_teams(cluster, team_ids, include_config=include_config)
