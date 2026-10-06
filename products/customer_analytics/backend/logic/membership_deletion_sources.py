from __future__ import annotations

import json
import hashlib
from collections.abc import Sequence
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models.person.util import PersonTombstone, get_person_tombstones
from posthog.personhog_client.client import require_personhog_client
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG, GetPersonsRequest, ReadOptions

from products.customer_analytics.backend.facade.membership_deletion_contracts import MembershipDeletionKind
from products.customer_analytics.backend.logic.membership_deletion_receipts import (
    confirm_membership_deletion,
    has_registered_membership_team,
    prepare_membership_deletion,
)
from products.customer_analytics.backend.models.membership_deletion import (
    MembershipDeletionIdentity,
    MembershipDeletionReceipt,
)

logger = structlog.get_logger(__name__)
PERSONHOG_TIMEOUT_SECONDS = 30
PERSONHOG_READ_BATCH_SIZE = 250
PERSONHOG_DELETE_BATCH_SIZE = 1000


class MembershipDeletionSources:
    @staticmethod
    def is_enabled() -> bool:
        return bool(getattr(settings, "CUSTOMER_ANALYTICS_MEMBERSHIP_DELETION_ENABLED", False))

    @classmethod
    def captures_team(cls, team_id: int) -> bool:
        return cls.is_enabled() and has_registered_membership_team(team_id)

    @classmethod
    def create_person_intents(cls, team_id: int, person_uuids: Sequence[UUID]) -> str | None:
        if not person_uuids or not cls.captures_team(team_id):
            return None
        source_key = f"profile:{uuid4()}"
        MembershipDeletionReceipt.objects.for_team(team_id).bulk_create(
            [
                MembershipDeletionReceipt(
                    team_id=team_id,
                    kind=MembershipDeletionKind.PERSON,
                    source_key=source_key,
                    person_uuid=person_uuid,
                )
                for person_uuid in dict.fromkeys(person_uuids)
            ],
            batch_size=1000,
        )
        return source_key

    @classmethod
    def record_tombstones(
        cls,
        team_id: int,
        tombstones: Sequence[PersonTombstone],
        *,
        source_key: str | None = None,
        required: bool = False,
    ) -> None:
        if not tombstones or not cls.is_enabled():
            return
        try:
            if not has_registered_membership_team(team_id):
                return
            cls._record_tombstones(team_id, tombstones, source_key)
        except Exception as error:
            if required:
                raise
            logger.error(  # noqa: TRY400 - database exceptions can contain bound distinct IDs
                "membership_deletion_receipt_capture_failed",
                team_id=team_id,
                person_count=len(tombstones),
                exception_type=type(error).__name__,
            )

    @staticmethod
    def _record_tombstones(team_id: int, tombstones: Sequence[PersonTombstone], source_key: str | None) -> None:
        keyed = {
            (source_key or f"tombstone:{tombstone.uuid}:{tombstone.version}", tombstone.uuid): tombstone
            for tombstone in tombstones
        }
        with transaction.atomic():
            receipts = MembershipDeletionReceipt.objects.for_team(team_id)
            receipts.bulk_create(
                [
                    MembershipDeletionReceipt(
                        team_id=team_id,
                        kind=MembershipDeletionKind.PERSON,
                        source_key=key,
                        person_uuid=person_uuid,
                    )
                    for key, person_uuid in keyed
                ],
                ignore_conflicts=True,
                batch_size=1000,
            )
            rows = list(
                receipts.select_for_update()
                .filter(kind=MembershipDeletionKind.PERSON, source_key__in={key for key, _ in keyed})
                .order_by("id")
            )
            identities: list[MembershipDeletionIdentity] = []
            changed: list[MembershipDeletionReceipt] = []
            for receipt in rows:
                tombstone = keyed.get((receipt.source_key, receipt.person_uuid))
                if tombstone is None:
                    continue
                if receipt.confirmed_at is not None:
                    if receipt.person_version != tombstone.version:
                        raise ValueError("Deletion source has a different person version")
                    continue
                identity_versions: dict[str, int] = {}
                for identity in tombstone.distinct_ids:
                    if len(identity.id) > 400:
                        raise ValueError("Membership identity exceeds 400 characters")
                    if identity.id in identity_versions and identity_versions[identity.id] != identity.version:
                        raise ValueError("Tombstone contains conflicting identity versions")
                    identity_versions[identity.id] = identity.version
                identities.extend(
                    MembershipDeletionIdentity(
                        team_id=team_id,
                        receipt_id=receipt.id,
                        distinct_id=distinct_id,
                        version=version,
                    )
                    for distinct_id, version in sorted(identity_versions.items())
                )
                receipt.person_version = tombstone.version
                receipt.identity_digest = hashlib.sha256(
                    json.dumps(sorted(identity_versions.items()), ensure_ascii=True).encode()
                ).hexdigest()
                receipt.confirmed_at = timezone.now()
                changed.append(receipt)
            MembershipDeletionIdentity.objects.for_team(team_id).bulk_create(identities, batch_size=1000)
            receipts.bulk_update(changed, ["person_version", "identity_digest", "confirmed_at"], batch_size=250)

    @classmethod
    def capture_before_purge(cls, team_id: int, person_uuids: Sequence[str]) -> None:
        if not person_uuids or not cls.captures_team(team_id):
            return
        for start in range(0, len(person_uuids), PERSONHOG_DELETE_BATCH_SIZE):
            tombstones = get_person_tombstones(
                team_id, [UUID(value) for value in person_uuids[start : start + PERSONHOG_DELETE_BATCH_SIZE]]
            )
            cls.record_tombstones(team_id, tombstones, required=True)

    @classmethod
    def record_team_deletion(cls, team_ids: Sequence[int]) -> None:
        if not cls.is_enabled():
            return
        for team_id in team_ids:
            if not has_registered_membership_team(team_id):
                continue
            receipt_id = prepare_membership_deletion(team_id, MembershipDeletionKind.TEAM, f"team_record:{team_id}")
            confirm_membership_deletion(team_id, receipt_id)

    @classmethod
    def create_team_persons_intent(cls, team_id: int, source_key: str) -> UUID | None:
        if not cls.captures_team(team_id):
            return None
        operation = hashlib.sha256(source_key.encode()).hexdigest()
        return prepare_membership_deletion(team_id, MembershipDeletionKind.TEAM_PERSONS, f"whole-team:{operation}")

    @staticmethod
    def confirm_team_persons_purge(team_id: int, receipt_id: UUID | None, *, exhausted: bool) -> None:
        if receipt_id is not None and exhausted:
            confirm_membership_deletion(team_id, receipt_id)

    @classmethod
    def tombstone_persons(cls, team_id: int, person_ids: Sequence[int], source_key: str) -> int:
        from posthog.models.person.bulk_delete import (  # noqa: PLC0415 - bulk_delete imports this source capture facade
            tombstone_and_publish_persons_by_uuids,
        )

        client = require_personhog_client()
        receipts = MembershipDeletionReceipt.objects.for_team(team_id)
        operation = hashlib.sha256(source_key.encode()).hexdigest()
        keys = {person_id: f"purge:{operation}:{person_id}" for person_id in person_ids}
        stored = {
            row.source_key: row.person_uuid
            for row in receipts.filter(kind=MembershipDeletionKind.PERSON, source_key__in=keys.values())
        }
        missing = [person_id for person_id, key in keys.items() if key not in stored]
        for start in range(0, len(missing), PERSONHOG_READ_BATCH_SIZE):
            response = client.get_persons(
                GetPersonsRequest(
                    team_id=team_id,
                    person_ids=list(missing[start : start + PERSONHOG_READ_BATCH_SIZE]),
                    read_options=ReadOptions(consistency=CONSISTENCY_LEVEL_STRONG),
                )
            )
            new_receipts = [
                MembershipDeletionReceipt(
                    team_id=team_id,
                    kind=MembershipDeletionKind.PERSON,
                    source_key=keys[person.id],
                    person_uuid=UUID(person.uuid),
                )
                for person in response.persons
            ]
            receipts.bulk_create(new_receipts, ignore_conflicts=True, batch_size=1000)
        targets: list[tuple[str, UUID]] = []
        for receipt in receipts.filter(kind=MembershipDeletionKind.PERSON, source_key__in=keys.values()).order_by(
            "source_key"
        ):
            if receipt.person_uuid is None:
                raise ValueError("Person purge receipt has no person UUID")
            targets.append((receipt.source_key, receipt.person_uuid))
        deleted = 0
        for start in range(0, len(targets), PERSONHOG_DELETE_BATCH_SIZE):
            batch = targets[start : start + PERSONHOG_DELETE_BATCH_SIZE]
            uuids = [str(person_uuid) for _, person_uuid in batch]
            deleted += tombstone_and_publish_persons_by_uuids(team_id, uuids)
            tombstones = {
                tombstone.uuid: tombstone for tombstone in get_person_tombstones(team_id, [u for _, u in batch])
            }
            for key, person_uuid in batch:
                tombstone = tombstones.get(person_uuid)
                if tombstone is not None:
                    cls.record_tombstones(team_id, [tombstone], source_key=key, required=True)
        return deleted
