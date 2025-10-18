import logging
from typing import Any, Optional

from django.db import connections, models, router, transaction
from django.db.models import F, Q

from posthog.models.utils import UUIDT

from ..team import Team
from .missing_person import uuidFromDistinctId

logger = logging.getLogger(__name__)

MAX_LIMIT_DISTINCT_IDS = 2500

if "persons_db_reader" in connections:
    READ_DB_FOR_PERSONS = "persons_db_reader"
elif "replica" in connections:
    READ_DB_FOR_PERSONS = "replica"
else:
    READ_DB_FOR_PERSONS = "default"


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic(using=self.db):
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
            return person


class Person(models.Model):
    id = models.BigAutoField(primary_key=True)
    _distinct_ids: Optional[list[str]]

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation = models.JSONField(null=True, blank=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)

    # current version of the person, used to sync with ClickHouse and collapse rows correctly
    version = models.BigIntegerField(null=True, blank=True)

    # Has an index on properties -> email from migration 0121, (team_id, id DESC) from migration 0164

    objects = PersonManager()

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False

    @property
    def distinct_ids(self) -> list[str]:
        if hasattr(self, "distinct_ids_cache"):
            return [id.distinct_id for id in self.distinct_ids_cache]
        if hasattr(self, "_distinct_ids") and self._distinct_ids:
            return self._distinct_ids
        return [
            id[0]
            for id in PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=self, team_id=self.team_id)
            .order_by("id")
            .values_list("distinct_id")
        ]

    @property
    def email(self) -> Optional[str]:
        return self.properties.get("email")

    # :DEPRECATED: This should happen through the plugin server
    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team_id=self.team_id)

    # :DEPRECATED: This should happen through the plugin server
    def _add_distinct_ids(self, distinct_ids: list[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    def split_person(self, main_distinct_id: Optional[str], max_splits: Optional[int] = None):
        original_person = Person.objects.get(pk=self.pk)

        # Log which database we're reading distinct_ids from
        logger.info(
            "split_person: Fetching distinct_ids",
            extra={
                "person_id": self.pk,
                "person_uuid": str(self.uuid),
                "team_id": self.team_id,
                "read_db": READ_DB_FOR_PERSONS,
            },
        )

        distinct_ids = original_person.distinct_ids
        original_person_version = original_person.version or 0

        # Also fetch from the write database to compare
        db_alias_write = router.db_for_write(PersonDistinctId) or "default"
        distinct_ids_from_write_db = [
            id[0]
            for id in PersonDistinctId.objects.db_manager(db_alias_write)
            .filter(person=self, team_id=self.team_id)
            .order_by("id")
            .values_list("distinct_id")
        ]

        # Check for discrepancies between read and write databases
        missing_from_read = set(distinct_ids_from_write_db) - set(distinct_ids)
        extra_in_read = set(distinct_ids) - set(distinct_ids_from_write_db)

        if missing_from_read or extra_in_read:
            logger.warning(
                "split_person: Discrepancy between read and write databases",
                extra={
                    "person_id": self.pk,
                    "read_db": READ_DB_FOR_PERSONS,
                    "write_db": db_alias_write,
                    "distinct_ids_from_read": distinct_ids,
                    "distinct_ids_from_write": distinct_ids_from_write_db,
                    "missing_from_read": list(missing_from_read),
                    "extra_in_read": list(extra_in_read),
                },
            )

        logger.info(
            "split_person: Starting person split",
            extra={
                "person_id": self.pk,
                "person_uuid": str(self.uuid),
                "team_id": self.team_id,
                "total_distinct_ids": len(distinct_ids),
                "distinct_ids": distinct_ids,
                "distinct_ids_from_write_db": distinct_ids_from_write_db,
                "read_db": READ_DB_FOR_PERSONS,
                "write_db": db_alias_write,
                "max_splits": max_splits,
                "original_person_version": original_person_version,
            },
        )

        if not main_distinct_id:
            self.properties = {}
            self.save()
            main_distinct_id = distinct_ids[0]
            logger.info(
                "split_person: No main_distinct_id provided, using first distinct_id",
                extra={"person_id": self.pk, "main_distinct_id": main_distinct_id},
            )
        else:
            logger.info(
                "split_person: Using provided main_distinct_id",
                extra={"person_id": self.pk, "main_distinct_id": main_distinct_id},
            )

        if max_splits is not None and len(distinct_ids) > max_splits:
            original_count = len(distinct_ids)
            distinct_ids = distinct_ids[-1 * max_splits :]
            logger.info(
                "split_person: Limiting splits due to max_splits",
                extra={
                    "person_id": self.pk,
                    "original_count": original_count,
                    "limited_count": len(distinct_ids),
                    "max_splits": max_splits,
                },
            )

        split_count = 0
        failed_count = 0
        skipped_count = 0

        for distinct_id in distinct_ids:
            if distinct_id == main_distinct_id:
                logger.info(
                    "split_person: Skipping main_distinct_id",
                    extra={"person_id": self.pk, "distinct_id": distinct_id},
                )
                skipped_count += 1
                continue

            try:
                logger.info(
                    "split_person: Processing distinct_id",
                    extra={"person_id": self.pk, "distinct_id": distinct_id},
                )

                db_alias = router.db_for_write(PersonDistinctId) or "default"

                with transaction.atomic(using=db_alias):
                    pdi = PersonDistinctId.objects.select_for_update().get(person=self, distinct_id=distinct_id)
                    person, created = Person.objects.get_or_create(
                        uuid=uuidFromDistinctId(self.team_id, distinct_id),
                        team_id=self.team_id,
                        defaults={
                            # Set version higher than delete events (which use version + 100).
                            # Keep in sync with: posthog/models/person/util.py:222 (_delete_person)
                            # and plugin-server/src/utils/db/utils.ts:152 (generateKafkaPersonUpdateMessage)
                            "version": original_person_version + 101,
                        },
                    )
                    pdi.person_id = str(person.id)
                    # Set distinct_id version higher than delete events (which use pdi.version + 100).
                    # This ensures the split distinct_id overrides any deleted distinct_id.
                    pdi.version = (pdi.version or 0) + 101
                    pdi.save(update_fields=["version", "person_id"])

                from posthog.models.person.util import create_person, create_person_distinct_id

                create_person_distinct_id(
                    team_id=self.team_id,
                    distinct_id=distinct_id,
                    person_id=str(person.uuid),
                    is_deleted=False,
                    version=pdi.version,
                )
                create_person(
                    team_id=self.team_id, uuid=str(person.uuid), version=person.version, created_at=person.created_at
                )

                split_count += 1
                logger.info(
                    "split_person: Successfully split distinct_id",
                    extra={
                        "person_id": self.pk,
                        "distinct_id": distinct_id,
                        "new_person_id": person.id,
                        "new_person_uuid": str(person.uuid),
                        "person_created": created,
                        "pdi_version": pdi.version,
                    },
                )
            except Exception as e:
                failed_count += 1
                logger.error(
                    "split_person: Failed to split distinct_id",
                    extra={
                        "person_id": self.pk,
                        "distinct_id": distinct_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )

        logger.info(
            "split_person: Completed person split",
            extra={
                "person_id": self.pk,
                "person_uuid": str(self.uuid),
                "team_id": self.team_id,
                "total_processed": len(distinct_ids),
                "split_count": split_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
            },
        )


class PersonDistinctId(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id = models.CharField(max_length=400)

    # current version of the id, used to sync with ClickHouse and collapse rows correctly for new clickhouse table
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [models.UniqueConstraint(fields=["team", "distinct_id"], name="unique distinct_id for team")]


class PersonlessDistinctId(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    distinct_id = models.CharField(max_length=400)
    is_merged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(fields=["team", "distinct_id"], name="unique personless distinct_id for team")
        ]


class PersonOverrideMapping(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    uuid = models.UUIDField()

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(fields=["team_id", "uuid"], name="unique_uuid"),
        ]


class PersonOverride(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    old_person_id = models.ForeignKey(
        "PersonOverrideMapping",
        db_column="old_person_id",
        related_name="person_override_old",
        on_delete=models.CASCADE,
    )
    override_person_id = models.ForeignKey(
        "PersonOverrideMapping",
        db_column="override_person_id",
        related_name="person_override_override",
        on_delete=models.CASCADE,
    )

    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(
                fields=["team", "old_person_id"],
                name="unique override per old_person_id",
            ),
            models.CheckConstraint(
                check=~Q(old_person_id__exact=F("override_person_id")),
                name="old_person_id_different_from_override_person_id",
            ),
        ]


class PendingPersonOverride(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False


class FlatPersonOverride(models.Model):
    # XXX: NOT USED, see https://github.com/PostHog/posthog/pull/23616

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        indexes = [
            models.Index(fields=["team_id", "override_person_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "old_person_id"],
                name="flatpersonoverride_unique_old_person_by_team",
            ),
            models.CheckConstraint(
                check=~Q(old_person_id__exact=F("override_person_id")),
                name="flatpersonoverride_check_circular_reference",
            ),
        ]


def get_distinct_ids_for_subquery(person: Person | None, team: Team) -> list[str]:
    """_summary_
    Fetching distinct_ids for a person from CH is slow, so we
    fetch them from PG for certain queries. Therfore we need
    to inline the ids in a `distinct_ids IN (...)` clause.

    This can cause the query to explode for persons with many
    ids. Thus we need to limit the amount of distinct_ids we
    pass through.

    The first distinct_ids should contain the real distinct_ids
    for a person and later ones should be associated with current
    events. Therefore we union from both sides.

    Many ids are usually a sign of instrumentation issues
    on the customer side.
    """
    first_ids_limit = 100
    last_ids_limit = MAX_LIMIT_DISTINCT_IDS - first_ids_limit

    if person is not None:
        first_ids = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=person, team=team)
            .order_by("id")
            .values_list("distinct_id", flat=True)[:first_ids_limit]
        )
        last_ids = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=person, team=team)
            .order_by("-id")
            .values_list("distinct_id", flat=True)[:last_ids_limit]
        )
        distinct_ids = first_ids.union(last_ids)
    else:
        distinct_ids = []
    return list(map(str, distinct_ids))
