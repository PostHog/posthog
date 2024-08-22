from typing import Any, Optional

from django.db import models, transaction
from django.db.models import F, Q

from posthog.models.utils import UUIDT

from ..team import Team
from .missing_person import uuidFromDistinctId

MAX_LIMIT_DISTINCT_IDS = 2500


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic(using=self.db):
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
            return person

    @staticmethod
    def distinct_ids_exist(team_id: int, distinct_ids: list[str]) -> bool:
        return PersonDistinctId.objects.filter(team_id=team_id, distinct_id__in=distinct_ids).exists()


class Person(models.Model):
    _distinct_ids: Optional[list[str]]

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation = models.JSONField(null=True, blank=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties = models.JSONField(default=dict)
    is_user = models.ForeignKey("User", on_delete=models.CASCADE, null=True, blank=True)
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)

    # current version of the person, used to sync with ClickHouse and collapse rows correctly
    version = models.BigIntegerField(null=True, blank=True)

    # Has an index on properties -> email from migration 0121, (team_id, id DESC) from migration 0164

    objects = PersonManager()

    @property
    def distinct_ids(self) -> list[str]:
        if hasattr(self, "distinct_ids_cache"):
            return [id.distinct_id for id in self.distinct_ids_cache]
        if hasattr(self, "_distinct_ids") and self._distinct_ids:
            return self._distinct_ids
        return [
            id[0]
            for id in PersonDistinctId.objects.filter(person=self, team_id=self.team_id)
            .order_by("id")
            .values_list("distinct_id")
        ]

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
                with transaction.atomic():
                    pdi = PersonDistinctId.objects.select_for_update().get(person=self, distinct_id=distinct_id)
                    person, _ = Person.objects.get_or_create(
                        uuid=uuidFromDistinctId(self.team_id, distinct_id),
                        team_id=self.team_id,
                        defaults={
                            "version": original_person_version + 1,
                        },
                    )
                    pdi.person_id = str(person.id)
                    pdi.version = (pdi.version or 0) + 1
                    pdi.save(update_fields=["version", "person_id"])

                from posthog.models.person.util import (
                    create_person,
                    create_person_distinct_id,
                )

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
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "distinct_id"], name="unique distinct_id for team")]

    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id = models.CharField(max_length=400)

    # current version of the id, used to sync with ClickHouse and collapse rows correctly for new clickhouse table
    version = models.BigIntegerField(null=True, blank=True)


class PersonlessDistinctId(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "distinct_id"], name="unique personless distinct_id for team")
        ]

    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    distinct_id = models.CharField(max_length=400)
    is_merged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)


class PersonOverrideMapping(models.Model):
    """A model of persons to be overriden in merge or merge-like events."""

    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    uuid = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "uuid"], name="unique_uuid"),
        ]


class PersonOverride(models.Model):
    """A model of persons to be overriden in merge or merge-like events.

    This model has a set of constraints to ensure correctness:
    1. Unique constraint on (team_id, old_person_id) pairs.
    2. Check that old_person_id is different to override_person_id for every row.
    3. Same person id cannot be used as an old_person_id and an override_person_id (per team)
       (e.g. if a row exists with old_person_id=123 then we would not allow a row with
        override_person_id=123 to exist, as that would require a self join to figure
        out the ultimate override_person_id required for old_person_id=123).
        To accomplish this we use a series of constraints.
    """

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
    """
    The pending person overrides model/table contains records of merges that
    have occurred, but have not yet been integrated into the person overrides
    table.

    This table should generally be considered as a log table or queue. When a
    merge occurs, it is recorded to the log (added to the queue) as part of the
    merge transaction. Later, another process comes along, reading from the
    other end of the log (popping from the queue) and applying the necessary
    updates to the person overrides table as part of secondary transaction.

    This approach allows us to decouple the set of operations that must occur as
    part of an atomic transactional unit during person merging (moving distinct
    IDs, merging properties, deleting the subsumed person, etc.) from those that
    are more tolerant to eventual consistency (updating person overrides in
    Postgres and subsequently relaying those updates to ClickHouse in various
    forms to update the person associated with an event.) This decoupling helps
    us to minimize the overhead of the primary merge transaction by reducing the
    degree of contention within the ingestion pipeline caused by long-running
    transactions. This decoupling also allows us to serialize the execution of
    all updates to the person overrides table through a single writer, which
    allows us to safely update the person overrides table while handling tricky
    cases like applying transitive updates without the need for expensive table
    constraints to ensure their validity.
    """

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()


class FlatPersonOverride(models.Model):
    """
    The (flat) person overrides model/table contains a consolidated record of
    all merges that have occurred, but have not yet been integrated into the
    ClickHouse events table through a squash operation. Once the effects of a
    merge have been integrated into the events table, the associated override
    record can be deleted from this table.

    This table is in some sense a materialized view over the pending person
    overrides table (i.e. the merge log.) It differs from that base table in
    that it should be maintained during updates to account for the effects of
    transitive merges. For example, if person A is merged into person B, and
    then person B is merged into person C, we'd expect the first record (A->B)
    to be updated to reflect that person A has been merged into person C (A->C,
    eliding the intermediate step.)

    There are several important expectations about the nature of the data within
    this table:

    * A person should only appear as an "old" person at most once for a given
      team (as appearing more than once would imply they were merged into
      multiple people.)
    * A person cannot be merged into themselves (i.e. be both the "old" and
      "override" person within a given row.)
    * A person should only appear in a table as _either_ an "old" person or
      "override" person for a given team -- but never both, as this would
      indicate a failure to account for a transitive merge.

    The first two of these expectations can be enforced as constraints, but
    unfortunately we've found the third to be too costly to enforce in practice.
    Instead, we try to ensure that this invariant holds by serializing all
    writes to this table through the ``PendingPersonOverride`` model above.

    The "flat" in the table name is used to distinguish this table from a prior
    approach that required multiple tables to maintain the same state but
    otherwise has little significance of its own.
    """

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
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
            PersonDistinctId.objects.filter(person=person, team=team)
            .order_by("id")
            .values_list("distinct_id", flat=True)[:first_ids_limit]
        )
        last_ids = (
            PersonDistinctId.objects.filter(person=person, team=team)
            .order_by("-id")
            .values_list("distinct_id", flat=True)[:last_ids_limit]
        )
        distinct_ids = first_ids.union(last_ids)
    else:
        distinct_ids = []
    return list(map(str, distinct_ids))
