from datetime import UTC, datetime
from typing import Any, NamedTuple, Optional
from uuid import UUID

from django.conf import settings
from django.core.exceptions import EmptyResultSet
from django.db import connections, models
from django.db.models import F, Q

import structlog

from posthog.models.utils import UUIDT

from ..team import Team

logger = structlog.get_logger(__name__)

MAX_LIMIT_DISTINCT_IDS = 2500

# Mirrors MAX_SPLIT_BATCH_SIZE enforced by the personhog SplitPerson RPC.
PERSONHOG_SPLIT_BATCH_SIZE = 250


class SplitOutcome(NamedTuple):
    """One distinct_id split onto a new person — the data needed to publish to Kafka."""

    distinct_id: str
    new_person_uuid: UUID
    new_person_version: int
    pdi_version: int
    new_person_created_at: datetime


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

    # Timestamp of when the person was last seen (last event timestamp)
    # Updated by ingestion pipeline when processing events
    last_seen_at = models.DateTimeField(null=True, blank=True)

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
        if hasattr(self, "_distinct_ids") and self._distinct_ids is not None:
            return self._distinct_ids
        raise ValueError("Person.distinct_ids requires _distinct_ids to be populated via personhog")

    @property
    def email(self) -> Optional[str]:
        return self.properties.get("email")

    def split_person(
        self,
        main_distinct_id: Optional[str],
        max_splits: Optional[int] = None,
        distinct_ids_to_split: Optional[list[str]] = None,
    ):
        """Split distinct_ids off of this person onto new persons.

        When ``distinct_ids_to_split`` is provided, only those specific distinct_ids are
        moved to new persons; the original person keeps all other distinct_ids and its
        properties intact. In that mode, ``main_distinct_id`` and ``max_splits`` are
        ignored. This is the "partial split" path — useful to surgically extract IDs
        that were over-merged into a mega-person.

        When ``distinct_ids_to_split`` is None, every distinct_id except
        ``main_distinct_id`` is split off (or only the first ``max_splits`` of them).
        If ``main_distinct_id`` is also None, the first distinct_id is kept. The
        original person always retains its properties.
        """
        from posthog.personhog_client.caller_tag import personhog_caller_tag
        from posthog.personhog_client.client import get_personhog_client
        from posthog.personhog_client.proto import GetPersonRequest

        client = get_personhog_client()
        if client is None:
            raise RuntimeError(
                "split_person requires personhog, but the client is not configured (PERSONHOG_ADDR is unset)"
            )

        # Tag every personhog call made during the split (get_person, the paged
        # get_distinct_ids_for_person, and the split_person RPCs) so the traffic is attributable.
        with personhog_caller_tag("persons/split"):
            person_resp = client.get_person(GetPersonRequest(team_id=self.team_id, person_id=self.pk))
            if not person_resp.person or not person_resp.person.id:
                raise ValueError(f"Person not found: person_id={self.pk}, team_id={self.team_id}")

            logger.info(
                "split_person queried person",
                person_id=self.pk,
                person_uuid=person_resp.person.uuid,
                team_id=self.team_id,
                version=person_resp.person.version,
                main_distinct_id=main_distinct_id,
                max_splits=max_splits,
                explicit_distinct_ids_count=len(distinct_ids_to_split) if distinct_ids_to_split is not None else None,
            )

            if distinct_ids_to_split is not None:
                self._split_explicit_ids(distinct_ids_to_split)
            else:
                self._split_all_ids(client, main_distinct_id, max_splits)

    def _split_explicit_ids(self, distinct_ids_to_split: list[str]) -> None:
        """Partial split: caller specifies exactly which IDs to move.

        The RPC validates that every ID belongs to this person — no need to
        fetch all distinct IDs upfront.
        """
        seen: set[str] = set()
        distinct_ids_to_process: list[str] = []
        for did in distinct_ids_to_split:
            if did not in seen:
                seen.add(did)
                distinct_ids_to_process.append(did)

        if not distinct_ids_to_process:
            return

        logger.info(
            "split_person will split explicit distinct_ids",
            person_id=self.pk,
            team_id=self.team_id,
            distinct_ids_to_split_count=len(distinct_ids_to_process),
        )

        for start in range(0, len(distinct_ids_to_process), PERSONHOG_SPLIT_BATCH_SIZE):
            batch = distinct_ids_to_process[start : start + PERSONHOG_SPLIT_BATCH_SIZE]
            outcomes = self._split_distinct_ids_batch(batch)
            self._publish_split_to_kafka(outcomes)

    def _split_all_ids(self, client: Any, main_distinct_id: Optional[str], max_splits: Optional[int]) -> None:
        """Full split: fetch pages of distinct IDs and split each page.

        Each split removes the IDs from this person, so the next fetch returns
        a shrinking set. No ordering is needed — the loop terminates when only
        the main distinct_id remains (or max_splits is reached).
        """
        from posthog.personhog_client.proto import GetDistinctIdsForPersonRequest

        splits_done = 0
        # +1 so the main_distinct_id can appear in the page without eating a split slot
        fetch_limit = PERSONHOG_SPLIT_BATCH_SIZE + 1

        while True:
            did_resp = client.get_distinct_ids_for_person(
                GetDistinctIdsForPersonRequest(
                    team_id=self.team_id,
                    person_id=self.pk,
                    limit=fetch_limit,
                )
            )
            page = [d.distinct_id for d in did_resp.distinct_ids]

            if not page:
                break

            if not main_distinct_id:
                main_distinct_id = page[0]

            to_split = [did for did in page if did != main_distinct_id]

            if not to_split:
                break

            if max_splits is not None:
                remaining = max_splits - splits_done
                if remaining <= 0:
                    break
                to_split = to_split[:remaining]

            logger.info(
                "split_person splitting page",
                person_id=self.pk,
                team_id=self.team_id,
                main_distinct_id=main_distinct_id,
                page_size=len(page),
                splitting_count=len(to_split),
                splits_done=splits_done,
            )

            outcomes = self._split_distinct_ids_batch(to_split)
            self._publish_split_to_kafka(outcomes)
            splits_done += len(outcomes)

            if len(page) < fetch_limit:
                break

    def _split_distinct_ids_batch(self, distinct_ids: list[str]) -> list[SplitOutcome]:
        """Split one batch of distinct_ids onto new persons via the personhog
        SplitPerson RPC. Personhog owns this write — there is no ORM path.

        The server creates each new person with a deterministic UUIDv5
        (matching ``uuidFromDistinctId``) and bumps versions by 101, higher
        than delete events (which use version + 100) so the split overrides
        any deleted rows. Keep in sync with:
        posthog/models/person/util.py (_delete_person) and
        rust/personhog-replica/src/storage/postgres/person.rs (SPLIT_VERSION_OFFSET).
        """
        from posthog.personhog_client.client import get_personhog_client
        from posthog.personhog_client.proto import SplitPersonRequest

        client = get_personhog_client()
        if client is None:
            raise RuntimeError(
                "split_person requires personhog, but the client is not configured (PERSONHOG_ADDR is unset)"
            )

        response = client.split_person(
            SplitPersonRequest(
                team_id=self.team_id,
                person_id=self.pk,
                distinct_ids_to_split=distinct_ids,
            )
        )
        if len(response.splits) != len(distinct_ids):
            logger.error(
                "split_person RPC returned unexpected number of splits",
                expected=len(distinct_ids),
                actual=len(response.splits),
                team_id=self.team_id,
                person_id=self.pk,
            )
        return [
            SplitOutcome(
                distinct_id=split.distinct_id,
                new_person_uuid=UUID(split.new_person_uuid),
                new_person_version=split.new_person_version,
                pdi_version=split.pdi_version,
                new_person_created_at=datetime.fromtimestamp(split.new_person_created_at_ms / 1000, tz=UTC),
            )
            for split in response.splits
        ]

    def _publish_split_to_kafka(self, outcomes: list[SplitOutcome]) -> None:
        """Publish Kafka messages for each split person and PDI reassignment."""
        from posthog.models.person.util import create_person, create_person_distinct_id

        for outcome in outcomes:
            create_person_distinct_id(
                team_id=self.team_id,
                distinct_id=outcome.distinct_id,
                person_id=str(outcome.new_person_uuid),
                is_deleted=False,
                version=outcome.pdi_version,
            )
            create_person(
                team_id=self.team_id,
                uuid=str(outcome.new_person_uuid),
                version=outcome.new_person_version,
                created_at=outcome.new_person_created_at,
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
                condition=~Q(old_person_id__exact=F("override_person_id")),
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
                condition=~Q(old_person_id__exact=F("override_person_id")),
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
        # When a Person comes from personhog (via proto_person_to_model), distinct IDs
        # are already populated on _distinct_ids — use them directly to avoid hitting
        # the Django ORM below, which would defeat the purpose of the personhog path.
        if hasattr(person, "_distinct_ids") and person._distinct_ids is not None:
            ids = person._distinct_ids
            if len(ids) <= MAX_LIMIT_DISTINCT_IDS:
                return ids
            return list(set(ids[:first_ids_limit] + ids[-last_ids_limit:]))

        raise ValueError("get_distinct_ids_for_subquery requires _distinct_ids to be populated via personhog")

    return []
