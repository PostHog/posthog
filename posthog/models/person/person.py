from typing import Any, Optional

from django.conf import settings
from django.core.exceptions import EmptyResultSet
from django.db import connections, models, router, transaction
from django.db.models import F, Q

from posthog.models.utils import UUIDT
from posthog.person_db_router import PERSONS_DB_FOR_READ

from ..team import Team
from .missing_person import uuidFromDistinctId

MAX_LIMIT_DISTINCT_IDS = 2500

# Use centralized database routing constant
READ_DB_FOR_PERSONS = PERSONS_DB_FOR_READ


class PersonQuerySet(models.QuerySet):
    """
    Custom QuerySet that enforces team_id filtering on all Person queries.

    Required for partitioned posthog_person_new table (64 hash partitions by team_id).
    Queries without team_id would scan all 64 partitions causing ~64x performance degradation.
    """

    def _fetch_all(self):
        """
        Intercept query execution to validate team_id is present in WHERE clause.
        This is called before any query evaluation (get, filter, update, delete, etc.).
        """
        if self._result_cache is None:
            has_filter = self._has_team_id_filter()
            if not has_filter:
                # Get SQL for debugging
                sql = str(self.query)
                raise ValueError(
                    f"Person query missing required team_id filter. "
                    f"Partitioned table requires team_id for efficient querying. "
                    f"Add .filter(team_id=...) or .filter(team=...) to your query.\n"
                    f"Query SQL: {sql[:500]}"
                )
        return super()._fetch_all()

    def delete(self):
        """
        Intercept delete operations to ensure team_id filter is present.
        """
        has_filter = self._has_team_id_filter()
        if not has_filter:
            sql = str(self.query)
            raise ValueError(
                f"Person delete query missing required team_id filter. "
                f"Partitioned table requires team_id for efficient querying. "
                f"Add .filter(team_id=...) or .filter(team=...) before calling delete().\n"
                f"Query SQL: {sql[:500]}"
            )
        return super().delete()

    def update(self, **kwargs):
        """
        Intercept update operations to ensure team_id filter is present.
        """
        has_filter = self._has_team_id_filter()
        if not has_filter:
            sql = str(self.query)
            raise ValueError(
                f"Person update query missing required team_id filter. "
                f"Partitioned table requires team_id for efficient querying. "
                f"Add .filter(team_id=...) or .filter(team=...) before calling update().\n"
                f"Query SQL: {sql[:500]}"
            )
        return super().update(**kwargs)

    def _has_team_id_filter(self) -> bool:
        """
        Check if the query's WHERE clause contains a team_id filter.
        Walks the WHERE clause tree looking for team_id or team__id lookups.
        """
        if not self.query.where:
            return False

        try:
            sql = str(self.query)
        except EmptyResultSet:
            # Query will return no results (WHERE clause always false like WHERE 0=1)
            # This is safe - won't scan partitions. Allow it through.
            return True

        # Extract the WHERE clause portion to check for team_id
        # Split on WHERE and check the portion after it
        sql_lower = sql.lower()
        if "where" not in sql_lower:
            return False

        # Get everything after WHERE keyword
        where_index = sql_lower.index("where")
        where_clause = sql_lower[where_index:]

        # Remove ORDER BY, LIMIT, etc. that come after WHERE
        for keyword in [" order by", " limit", " offset", " for update", " group by", " having"]:
            if keyword in where_clause:
                where_clause = where_clause[: where_clause.index(keyword)]

        # Check if team_id appears in the WHERE clause
        # This catches: team_id = X, team_id IN (...), team.id = X, etc.
        return "team_id" in where_clause or "team.id" in where_clause


class PersonManager(models.Manager):
    # Comment out the below to add our detector for queries not using the team_id filter
    # def get_queryset(self):
    #     """Return PersonQuerySet with team_id enforcement."""
    #     return PersonQuerySet(self.model, using=self._db)

    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic(using=self.db):
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
            return person

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        # For composite PK tables, pre-generate IDs from the sequence
        # Django's bulk_create tries to INSERT id=NULL which violates NOT NULL constraint
        # This is a workaround to generate IDs for the persons database during tests/generate_demo_data

        objs_needing_ids = [obj for obj in objs if obj.id is None]
        if objs_needing_ids:
            # Use the persons database connection
            with connections[self.db].cursor() as cursor:
                cursor.execute(
                    "SELECT nextval('posthog_person_id_seq') FROM generate_series(1, %s)",
                    [len(objs_needing_ids)],
                )
                new_ids = [row[0] for row in cursor.fetchall()]
                for obj, new_id in zip(objs_needing_ids, new_ids):
                    obj.id = new_id
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class Person(models.Model):
    # Note: In posthog_person_new (partitioned table), the PK is composite: (team_id, id)
    # Django doesn't fully support composite PKs, so we mark id as primary_key for ORM compatibility
    # but the actual database constraint is on (team_id, id)
    id = models.BigAutoField(primary_key=True)
    _distinct_ids: Optional[list[str]]

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation = models.JSONField(null=True, blank=True)

    # DO_NOTHING: Team deletion handled manually via Person.objects.filter(team_id=...).delete()
    # in delete_bulky_postgres_data(). Django CASCADE doesn't work across separate databases.
    # db_constraint=False: No database FK constraint - Person may live in separate database from Team
    team = models.ForeignKey("Team", on_delete=models.DO_NOTHING, db_constraint=False)
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
        db_table = settings.PERSON_TABLE_NAME
        # Note: Database has composite PK (team_id, id) but Django doesn't support declaring it
        constraints = [
            # Composite PK constraint exists in database but can't be declared in Django
            # models.UniqueConstraint(fields=["team_id", "id"], name="posthog_person_new_pkey")
        ]

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

    def delete(self, using=None, keep_parents=False):
        """
        Override delete to ensure team_id is in WHERE clause for partitioned tables.

        For partitioned tables (posthog_person_new), the default delete generates:
        DELETE FROM posthog_person WHERE id = X, which scans all 64 partitions.

        This implementation ensures single-partition access:
        DELETE FROM posthog_person WHERE team_id = Y AND id = X
        """
        if self.pk is None:
            raise ValueError(
                f"{self._meta.object_name} object can't be deleted because its {self._meta.pk.attname} attribute is set "
                "to None."
            )

        # Save pk and team_id before they get cleared by collector
        person_pk = self.pk
        person_team_id = self.team_id

        using = using or router.db_for_write(self.__class__, instance=self)

        with transaction.atomic(using=using):
            # Delete PersonDistinctId records with explicit team_id for partition pruning.
            # Django's Collector.delete() generates: DELETE FROM posthog_persondistinctid WHERE person_id IN (...)
            # which misses team_id and would scan all partitions on a partitioned table.
            PersonDistinctId.objects.filter(team_id=person_team_id, person_id=person_pk).delete()

            # Now delete the Person itself with explicit team_id for partition pruning
            db_connection = connections[using]
            with db_connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {self._meta.db_table} WHERE team_id = %s AND id = %s", [person_team_id, person_pk]
                )

        # Return the same format as Django's delete: (num_deleted, {model: count})
        return (1, {self._meta.label: 1})

    # :DEPRECATED: This should happen through the plugin server
    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team_id=self.team_id)

    # :DEPRECATED: This should happen through the plugin server
    def _add_distinct_ids(self, distinct_ids: list[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    def split_person(self, main_distinct_id: Optional[str], max_splits: Optional[int] = None):
        original_person = Person.objects.get(team_id=self.team_id, pk=self.pk)
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
    # DO_NOTHING + db_constraint=False: Team deletion handled manually, may be cross-database
    team = models.ForeignKey("Team", on_delete=models.DO_NOTHING, db_index=False, db_constraint=False)
    # db_constraint=False: FK constraint managed manually at database level as composite key
    # Database has: FOREIGN KEY (team_id, person_id) REFERENCES posthog_person(team_id, id)
    # This composite FK enables partition pruning on the partitioned person table
    person = models.ForeignKey(Person, on_delete=models.CASCADE, db_constraint=False)
    distinct_id = models.CharField(max_length=400)

    # current version of the id, used to sync with ClickHouse and collapse rows correctly for new clickhouse table
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [models.UniqueConstraint(fields=["team", "distinct_id"], name="unique distinct_id for team")]


class PersonlessDistinctId(models.Model):
    id = models.BigAutoField(primary_key=True)
    # DO_NOTHING + db_constraint=False: Team deletion handled manually, may be cross-database
    team = models.ForeignKey("Team", on_delete=models.DO_NOTHING, db_index=False, db_constraint=False)
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
    # DO_NOTHING + db_constraint=False: Team deletion handled manually, may be cross-database
    team = models.ForeignKey("Team", on_delete=models.DO_NOTHING, db_constraint=False)

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
