from typing import Any, Optional

from django.db import connections, models, router, transaction
from django.db.models import F, Q

from posthog.models.utils import UUIDT

from ..team import Team
from .missing_person import uuidFromDistinctId

MAX_LIMIT_DISTINCT_IDS = 2500
PERSON_ID_CUTOFF = 1000000000  # IDs < 1B in old table, >= 1B in new table

# Dual-table read preference: "old" = try old table first, "new" = try new table first
DUAL_TABLE_READ_PREFERENCE = "old"

if "persons_db_reader" in connections:
    READ_DB_FOR_PERSONS = "persons_db_reader"
elif "replica" in connections:
    READ_DB_FOR_PERSONS = "replica"
else:
    READ_DB_FOR_PERSONS = "default"


class PersonOld(models.Model):
    """Old non-partitioned person table (posthog_person)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)
    properties_last_operation = models.JSONField(null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "posthog_person"


class PersonNew(models.Model):
    """New hash-partitioned person table (posthog_person_new)."""

    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)
    properties_last_operation = models.JSONField(null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "posthog_person_new"


class DualPersonManager(models.Manager):
    """Manager that reads from both person tables during migration.

    Provides dual-table read support by:
    - get(): Tries preferred table first (configurable), falls back to other
    - filter(): Returns UNION of both tables (QuerySet, but limited operations)
    - Helper methods for explicit routing (get_by_id, get_by_uuid)
    """

    def get(self, *args, **kwargs):
        """Get person from either table, trying preferred table first.

        Supports special cases:
        - pk=X where X >= 1B: MUST be in new table (can route directly)
        - pk=X where X < 1B: Could be in either, check preferred first
        - Other kwargs: try preferred table first, fallback to other
        """
        # If pk >= cutoff, we KNOW it's in new table
        if "pk" in kwargs and kwargs["pk"] >= PERSON_ID_CUTOFF:
            person = PersonNew.objects.get(*args, **kwargs)
            person.__class__ = Person
            return person

        # Otherwise try preferred table first
        first_model = PersonOld if DUAL_TABLE_READ_PREFERENCE == "old" else PersonNew
        second_model = PersonNew if DUAL_TABLE_READ_PREFERENCE == "old" else PersonOld

        try:
            person = first_model.objects.get(*args, **kwargs)
            person.__class__ = Person
            return person
        except first_model.DoesNotExist:
            try:
                person = second_model.objects.get(*args, **kwargs)
                person.__class__ = Person
                return person
            except second_model.DoesNotExist:
                raise Person.DoesNotExist()

    def filter(self, *args, **kwargs):
        """Filter across both tables, returning UNION QuerySet.

        Note: Union QuerySets have limited operations:
        - Can iterate (for loops work)
        - Can't chain most filters after union
        - Can't use .count(), .update(), .delete() on union
        - Can't use .prefetch_related(), .select_related()

        Call sites needing these operations should use get_by_id() or
        query tables individually.
        """
        old_qs = PersonOld.objects.filter(*args, **kwargs)
        new_qs = PersonNew.objects.filter(*args, **kwargs)
        return old_qs.union(new_qs)

    def get_by_id(self, person_id: int, team_id: Optional[int] = None):
        """Get person by ID, routing based on ID cutoff.

        IDs >= cutoff MUST be in new table.
        IDs < cutoff could be in either, check preferred first.
        """
        if person_id >= PERSON_ID_CUTOFF:
            # MUST be in new table
            query = PersonNew.objects.filter(id=person_id)
            if team_id is not None:
                query = query.filter(team_id=team_id)
            result = query.first()
        else:
            # Could be in either, try preferred first
            first_model = PersonOld if DUAL_TABLE_READ_PREFERENCE == "old" else PersonNew
            second_model = PersonNew if DUAL_TABLE_READ_PREFERENCE == "old" else PersonOld

            query = first_model.objects.filter(id=person_id)
            if team_id is not None:
                query = query.filter(team_id=team_id)
            result = query.first()

            if not result:
                query = second_model.objects.filter(id=person_id)
                if team_id is not None:
                    query = query.filter(team_id=team_id)
                result = query.first()

        # Convert to Person instance for compatibility with FK relations
        if result:
            result.__class__ = Person
        return result

    def get_by_uuid(self, team_id: int, uuid: str):
        """Get person by UUID, trying new table first then falling back to old."""
        person = PersonNew.objects.filter(team_id=team_id, uuid=uuid).first()
        if not person:
            person = PersonOld.objects.filter(team_id=team_id, uuid=uuid).first()
        # Convert to Person instance for compatibility with FK relations
        if person:
            person.__class__ = Person
        return person


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

    objects = DualPersonManager()
    legacy_objects = PersonManager()  # Keep old manager for backward compatibility

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        db_table = "posthog_person"  # Default table, DualPersonManager routes reads based on ID

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
        distinct_ids = original_person.distinct_ids
        original_person_version = original_person.version or 0
        if not main_distinct_id:
            self.properties = {}
            self.save()
            main_distinct_id = distinct_ids[0]

        if max_splits is not None and len(distinct_ids) > max_splits:
            # Split the last N distinct_ids of the list
            distinct_ids = distinct_ids[-1 * max_splits :]

        for distinct_id in distinct_ids:
            if not distinct_id == main_distinct_id:
                db_alias = router.db_for_write(PersonDistinctId) or "default"
                with transaction.atomic(using=db_alias):
                    pdi = PersonDistinctId.objects.select_for_update().get(person=self, distinct_id=distinct_id)
                    person, _ = Person.objects.get_or_create(
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
