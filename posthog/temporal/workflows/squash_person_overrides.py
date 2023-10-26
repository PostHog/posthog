import contextlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Iterable, NamedTuple
from uuid import UUID

import psycopg2
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.clickhouse.client.execute import sync_execute
from posthog.temporal.workflows.base import PostHogWorkflow

EPOCH = datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)

SELECT_PERSONS_TO_DELETE_QUERY = """
SELECT
    team_id,
    old_person_id,
    override_person_id,
    max(created_at) AS latest_created_at,
    max(version) AS latest_version,
    min(oldest_event) AS oldest_event_at
FROM
    {database}.person_overrides
WHERE
    created_at <= %(latest_created_at)s
GROUP BY
    team_id, old_person_id, override_person_id
"""

SELECT_LATEST_CREATED_AT_QUERY = """
SELECT
    max(created_at)
FROM {database}.person_overrides;
"""

CREATE_DICTIONARY_QUERY = """
CREATE OR REPLACE DICTIONARY {database}.{dictionary_name} ON CLUSTER {cluster_name} (
    `team_id` INT,
    `old_person_id` UUID,
    `override_person_id` UUID
)
PRIMARY KEY team_id, old_person_id
SOURCE(CLICKHOUSE(USER '{user}' PASSWORD '{password}' TABLE 'person_overrides' DB '{database}'))
LAYOUT(complex_key_hashed())
LIFETIME(0)
"""

SQUASH_EVENTS_QUERY = """
ALTER TABLE
    {database}.sharded_events
UPDATE
    person_id = dictGet('{database}.{dictionary_name}', 'override_person_id', (toInt32(team_id), person_id))
IN PARTITION
    %(partition_id)s
WHERE
    dictHas('{database}.{dictionary_name}', (toInt32(team_id), person_id))
    {team_id_filter}
    AND created_at <= %(latest_created_at)s;
"""

DROP_DICTIONARY_QUERY = """
DROP DICTIONARY {database}.{dictionary_name};
"""

DELETE_SQUASHED_PERSON_OVERRIDES_QUERY = """
ALTER TABLE
    {database}.person_overrides
DELETE WHERE
    old_person_id IN %(old_person_ids)s
    AND created_at <= %(latest_created_at)s;
"""

SELECT_CREATED_AT_FOR_PERSON_EVENT_QUERY = """
SELECT
    min(created_at) AS oldest_event_at
FROM
    {database}.sharded_events
WHERE
    team_id = %(team_id)s
    AND person_id = %(old_person_id)s
    -- Not necessary, but can speed up query.
    AND created_at <= %(oldest_event_at)s
    AND created_at >= 0;
"""

SELECT_ID_FROM_OVERRIDE_UUID = """
SELECT
    id
FROM
    posthog_personoverridemapping
WHERE
    team_id = %(team_id)s
    AND uuid = %(uuid)s;
"""

DELETE_FROM_PERSON_OVERRIDES = """
DELETE FROM
    posthog_personoverride
WHERE
    team_id = %(team_id)s
    AND old_person_id = %(old_person_id)s
    AND override_person_id = %(override_person_id)s
    AND version = %(latest_version)s
RETURNING
    old_person_id;
"""

DELETE_FROM_PERSON_OVERRIDE_MAPPINGS = """
DELETE FROM
    posthog_personoverridemapping
WHERE
    id = %(id)s;
"""


class PersonOverrideToDelete(NamedTuple):
    """A person override that should be deleted after squashing.

    Attributes:
        team_id: The id of the team that the person belongs to.
        old_person_id: The uuid of the person being overriden.
        override_person_id: The uuid of the person used as the override.
        latest_created_at: The latest override timestamp for overrides with this pair of ids. This is set by ClickHouse on INSERT.
        latest_version: The latest version for overrides with this pair of ids.
        oldest_event_at: The creation date of the oldest event for old_person_id.
    """

    team_id: int
    old_person_id: UUID
    override_person_id: UUID
    latest_created_at: datetime
    latest_version: int
    oldest_event_at: datetime

    def _make_serializable(self) -> "SerializablePersonOverrideToDelete":
        return SerializablePersonOverrideToDelete._make(
            value.isoformat() if isinstance(value, datetime) else value for value in self
        )

    def is_in_partitions(self, partition_ids: list[str]):
        """Check if this PersonOverrideToDelete's oldest_event_at is in a list of partitions."""
        return self.oldest_event_at.strftime("%Y%m") in partition_ids


class SerializablePersonOverrideToDelete(NamedTuple):
    """A JSON serializable version of PersonOverrideToDelete.

    Only datetime types from PersonOverrideToDelete are not serializable by temporal's JSON
    encoder.
    """

    team_id: int
    old_person_id: UUID
    override_person_id: UUID
    latest_created_at: str
    latest_version: int
    oldest_event_at: str


@dataclass
class QueryInputs:
    """Inputs for activities that run queries in the SquashPersonOverrides workflow.

    Attributes:
        clickhouse: Inputs required to connect to ClickHouse.
        postgres: Inputs required to connect to Postgres.
        partition_ids: When necessary, the partition ids this query should run on.
        person_overrides_to_delete: For delete queries, a list of PersonOverrideToDelete.
        database: The database where the query is supposed to run.
        user: Database username required to create a dictionary.
        password: Database password required to create a dictionary.
        dictionary_name: The name for a dictionary used in the join.
        _latest_merged_at: A timestamp representing an upper bound for events to squash. Obtained
            as the latest timestamp of a person merge.
    """

    partition_ids: list[str] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    person_overrides_to_delete: list[SerializablePersonOverrideToDelete] = field(default_factory=list)
    dictionary_name: str = "person_overrides_join_dict"
    dry_run: bool = True
    _latest_created_at: str | datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self._latest_created_at, datetime):
            self.latest_created_at = self._latest_created_at

    @property
    def latest_created_at(self) -> datetime | None:
        if isinstance(self._latest_created_at, str):
            return datetime.fromisoformat(self._latest_created_at)
        return self._latest_created_at

    @latest_created_at.setter
    def latest_created_at(self, v: datetime | str | None) -> None:
        if isinstance(v, datetime):
            self._latest_created_at = v.isoformat()
        else:
            self._latest_created_at = v

    def iter_person_overides_to_delete(self) -> Iterable[SerializablePersonOverrideToDelete]:
        """Iterate over SerializablePersonOverrideToDelete ensuring they are of that type.

        Looking at the types, this seems pointless, just iterate over person_overrides_to_delete!
        However, as Temporal passes inputs to and from activities, namedtuples will be cast to
        lists. This method thus exists to transform them back into namedtuples.
        """
        for person_override_to_delete in self.person_overrides_to_delete:
            yield SerializablePersonOverrideToDelete(*person_override_to_delete)


@activity.defn
async def prepare_person_overrides(inputs: QueryInputs) -> None:
    """Prepare the person_overrides table to be used in a squash.

    This activity executes an OPTIMIZE TABLE query to ensure we assign the latest overrides for each old_person_id.
    """
    from django.conf import settings

    activity.logger.info("Preparing person_overrides table for squashing")

    optimize_query = "OPTIMIZE TABLE {database}.person_overrides ON CLUSTER {cluster} FINAL SETTINGS mutations_sync = 2"

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be detached or optimized.")
        activity.logger.info("Would have run query: %s", optimize_query)
        return

    activity.logger.info("Optimizing person_overrides")

    sync_execute(optimize_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER))


@activity.defn
async def prepare_dictionary(inputs: QueryInputs) -> str:
    """Prepare the DICTIONARY to be used in the squash workflow.

    We also lock in the latest merged_at to ensure we do not process overrides that arrive after
    we have started the job.
    """
    from django.conf import settings

    activity.logger.info("Preparing DICTIONARY %s", inputs.dictionary_name)
    latest_created_at = sync_execute(SELECT_LATEST_CREATED_AT_QUERY.format(database=settings.CLICKHOUSE_DATABASE))[0][0]

    activity.logger.info("Creating DICTIONARY %s", inputs.dictionary_name)
    sync_execute(
        CREATE_DICTIONARY_QUERY.format(
            database=settings.CLICKHOUSE_DATABASE,
            dictionary_name=inputs.dictionary_name,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            cluster_name=settings.CLICKHOUSE_CLUSTER,
        )
    )

    return latest_created_at.isoformat()


@activity.defn
async def drop_dictionary(inputs: QueryInputs) -> None:
    """DROP the DICTIONARY used in the squash workflow."""
    from django.conf import settings

    activity.logger.info("Dropping DICTIONARY %s", inputs.dictionary_name)
    sync_execute(
        DROP_DICTIONARY_QUERY.format(
            database=settings.CLICKHOUSE_DATABASE,
            dictionary_name=inputs.dictionary_name,
        )
    )


@activity.defn
async def select_persons_to_delete(inputs: QueryInputs) -> list[SerializablePersonOverrideToDelete]:
    """Select the persons we'll override to lock them in and safely delete afterwards

    New overrides may come in while we are executing this workflow, so we need to
    preemptively select which persons we are going to override to ignore any new ones
    coming in.

    It's important that we only select those persons for which the first partition_id
    in which they appear is covered by the current squash workflow. Otherwise, if there
    is an override in an older partition that is not covered by the current workflow
    we want to keep the override as there could still be events to squash.

    The output of this activity is a dictionary that maps integer team_ids to sets of
    person ids that are safe to delete. Team_id is used as a filter in later queries.
    """
    from django.conf import settings

    latest_created_at = inputs.latest_created_at.timestamp() if inputs.latest_created_at else inputs.latest_created_at
    to_delete_rows = sync_execute(
        SELECT_PERSONS_TO_DELETE_QUERY.format(database=settings.CLICKHOUSE_DATABASE),
        # We pass this as a timestamp ourselves as clickhouse-driver will drop any microseconds from the datetime.
        # This would cause the latest merge event to be ignored.
        # See: https://github.com/mymarilyn/clickhouse-driver/issues/306
        {"latest_created_at": latest_created_at},
    )

    if not isinstance(to_delete_rows, list):
        # Could return None if no results or int if this were an insert.
        # Mostly to appease type checker
        return []

    # We need to be absolutely sure which is the oldest event for a given person
    # as we cannot delete persons that have events in the past that aren't being
    # squashed by this workflow.
    persons_to_delete = []
    older_persons_to_delete = []
    for row in to_delete_rows:
        person_to_delete = PersonOverrideToDelete._make(row)
        person_oldest_event_at = person_to_delete.oldest_event_at

        try:
            absolute_oldest_event_at = sync_execute(
                SELECT_CREATED_AT_FOR_PERSON_EVENT_QUERY.format(database=settings.CLICKHOUSE_DATABASE),
                {
                    "team_id": person_to_delete.team_id,
                    "old_person_id": person_to_delete.old_person_id,
                    "oldest_event_at": person_oldest_event_at,
                },
            )[0][0]

        except IndexError:
            # Let's be safe and treat this as no rows found.
            absolute_oldest_event_at = EPOCH

        # ClickHouse min() likes to return the epoch when no rows found.
        # Granted, I'm assuming that we were not ingesting events in 1970...
        if absolute_oldest_event_at != EPOCH:
            min_oldest_event_at = min(
                person_oldest_event_at,
                absolute_oldest_event_at,
            )
        else:
            min_oldest_event_at = person_oldest_event_at

        person_to_delete = person_to_delete._replace(oldest_event_at=min_oldest_event_at)

        if person_to_delete.is_in_partitions(inputs.partition_ids):
            persons_to_delete.append(person_to_delete._make_serializable())
        else:
            older_persons_to_delete.append(person_to_delete)

    # There could be older overrides that we haven't cleaned up yet.
    # As the squash logic will always prefer new ones, there is no reason to keep the
    # older ones around if we schedule the old ones to be deleted.
    # So, let's delete those too.
    persons_to_delete_ids = set(person.old_person_id for person in persons_to_delete)
    persons_to_delete.extend(
        (
            older_person._make_serializable()
            for older_person in older_persons_to_delete
            if older_person.old_person_id in persons_to_delete_ids
        )
    )

    return persons_to_delete


@activity.defn
async def squash_events_partition(inputs: QueryInputs) -> None:
    """Execute the squash query for a given partition_id and persons to_override.

    As ClickHouse doesn't support an UPDATE ... FROM statement ala PostgreSQL, we must
    do this in 4 basic steps:

    1. Stop ingesting data into person_overrides.
    2. Build a DICTIONARY from person_overrides.
    3. Perform ALTER TABLE UPDATE using dictGet to query the DICTIONARY.
    4. Clean up the DICTIONARY once done.
    """
    from django.conf import settings

    query = SQUASH_EVENTS_QUERY

    latest_created_at = inputs.latest_created_at.timestamp() if inputs.latest_created_at else inputs.latest_created_at

    for partition_id in inputs.partition_ids:
        activity.logger.info("Executing squash query on partition %s", partition_id)

        parameters = {
            "partition_id": partition_id,
            "team_ids": inputs.team_ids,
            # We pass this as a timestamp ourselves as clickhouse-driver will drop any microseconds from the datetime.
            # This would cause the latest merge event to be ignored.
            # See: https://github.com/mymarilyn/clickhouse-driver/issues/306
            "latest_created_at": latest_created_at,
        }

        if inputs.dry_run is True:
            activity.logger.info("This is a DRY RUN so nothing will be squashed.")
            activity.logger.info("Would have run query: %s with parameters %s", query, parameters)
            continue

        sync_execute(
            query.format(
                database=settings.CLICKHOUSE_DATABASE,
                dictionary_name=inputs.dictionary_name,
                team_id_filter="AND team_id in %(team_ids)s" if inputs.team_ids else "",
            ),
            parameters,
        )


@activity.defn
async def delete_squashed_person_overrides_from_clickhouse(inputs: QueryInputs) -> None:
    """Execute the query to delete persons from ClickHouse that have been squashed."""
    from django.conf import settings

    activity.logger.info("Deleting squashed persons from ClickHouse")

    old_person_ids_to_delete = tuple(person.old_person_id for person in inputs.iter_person_overides_to_delete())
    activity.logger.debug("%s", old_person_ids_to_delete)

    query = DELETE_SQUASHED_PERSON_OVERRIDES_QUERY
    latest_created_at = inputs.latest_created_at.timestamp() if inputs.latest_created_at else inputs.latest_created_at
    parameters = {
        "old_person_ids": old_person_ids_to_delete,
        # We pass this as a timestamp ourselves as clickhouse-driver will drop any microseconds from the datetime.
        # This would cause the latest merge event to be ignored.
        # See: https://github.com/mymarilyn/clickhouse-driver/issues/306
        "latest_created_at": latest_created_at,
    }

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be deleted.")
        activity.logger.info("Would have run query: %s with parameters %s", query, parameters)
        return

    sync_execute(query.format(database=settings.CLICKHOUSE_DATABASE), parameters)


@activity.defn
async def delete_squashed_person_overrides_from_postgres(inputs: QueryInputs) -> None:
    """Execute the query to delete from Postgres persons that have been squashed.

    We cannot use the Django ORM in an async context without enabling unsafe behavior.
    This may be a good excuse to unshackle ourselves from the ORM.
    """
    from django.conf import settings

    activity.logger.info("Deleting squashed persons from Postgres")
    with psycopg2.connect(
        dbname=settings.DATABASES["default"]["NAME"],
        user=settings.DATABASES["default"]["USER"],
        password=settings.DATABASES["default"]["PASSWORD"],
        host=settings.DATABASES["default"]["HOST"],
        port=settings.DATABASES["default"]["PORT"],
        **settings.DATABASES["default"].get("SSL_OPTIONS", {}),
    ) as connection:
        with connection.cursor() as cursor:
            for person_override_to_delete in inputs.iter_person_overides_to_delete():
                activity.logger.debug("%s", person_override_to_delete)

                cursor.execute(
                    SELECT_ID_FROM_OVERRIDE_UUID,
                    {
                        "team_id": person_override_to_delete.team_id,
                        "uuid": person_override_to_delete.old_person_id,
                    },
                )

                row = cursor.fetchone()
                if not row:
                    continue
                old_person_id = row[0]

                cursor.execute(
                    SELECT_ID_FROM_OVERRIDE_UUID,
                    {
                        "team_id": person_override_to_delete.team_id,
                        "uuid": person_override_to_delete.override_person_id,
                    },
                )

                row = cursor.fetchone()
                if not row:
                    continue

                override_person_id = row[0]

                parameters = {
                    "team_id": person_override_to_delete.team_id,
                    "old_person_id": old_person_id,
                    "override_person_id": override_person_id,
                    "latest_version": person_override_to_delete.latest_version,
                }

                if inputs.dry_run is True:
                    activity.logger.info("This is a DRY RUN so nothing will be deleted.")
                    activity.logger.info(
                        "Would have run query: %s with parameters %s",
                        DELETE_FROM_PERSON_OVERRIDES,
                        parameters,
                    )
                    continue

                cursor.execute(DELETE_FROM_PERSON_OVERRIDES, parameters)

                row = cursor.fetchone()
                if not row:
                    # There is no existing mapping for this (old_person_id, override_person_id) pair.
                    # It could be that a newer one was added (with a later version).
                    continue
                deleted_id = row[0]

                cursor.execute(
                    DELETE_FROM_PERSON_OVERRIDE_MAPPINGS,
                    {
                        "id": deleted_id,
                    },
                )


@contextlib.asynccontextmanager
async def person_overrides_dictionary(
    workflow, query_inputs: QueryInputs, retry_policy: RetryPolicy
) -> AsyncIterator[str]:
    """This context manager manages the person_overrides DICTIONARY used during a squash job.

    Managing the DICTIONARY involves setup activities:
    - Prepare the underlying person_overrides table optimizing the table to remove any duplicates.
    - Creating the DICTIONARY itself, returning latest_created_at.

    And clean-up activities:
    - Dropping the DICTIONARY.

    It's important that we account for possible cancellations with a try/finally block. However, if the
    squash workflow is terminated instead of cancelled, we may leave the underlying dictionary un-dropped.
    There is nothing we can do about this as termination leaves us no time to clean-up.
    """
    await workflow.execute_activity(
        prepare_person_overrides,
        query_inputs,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=retry_policy,
    )
    latest_created_at = await workflow.execute_activity(
        prepare_dictionary,
        query_inputs,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=retry_policy,
    )

    try:
        yield latest_created_at

    finally:
        await workflow.execute_activity(
            drop_dictionary,
            query_inputs,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )


@dataclass
class SquashPersonOverridesInputs:
    """Inputs for the SquashPersonOverrides workflow.

    Attributes:
        clickhouse_database: The name of the ClickHouse database where to perform the squash.
        postgres_database: The name of the Postgres database where to delete overrides once done.
        dictionary_name: A name for the JOIN table created for the squash.
        team_ids: List of team ids to squash. If None, will squash all.
        partition_ids: Partitions to squash, preferred over last_n_months.
        last_n_months: Execute the squash on the partitions for the last_n_months.
        dry_run: If True, queries that mutate or delete data will not execute and instead will be logged.
    """

    team_ids: list[int] = field(default_factory=list)
    partition_ids: list[str] | None = None
    dictionary_name: str = "person_overrides_join_dict"
    last_n_months: int = 1
    dry_run: bool = True

    def iter_partition_ids(self) -> Iterator[str]:
        """Iterate over configured partition ids.

        If partition_ids is set, then we will just yield from that.
        Otherwise, we compute the partition keys for the last_n_months.
        """
        if self.partition_ids:
            yield from self.partition_ids
            return

        for month in self.iter_last_n_months():
            yield month.strftime("%Y%m")

    def iter_last_n_months(self) -> Iterator[datetime]:
        """Iterate over the last N months.

        Returns the first day of the last N months. The current month
        counts as the first month.
        """
        current_month = datetime.now()

        for _ in range(self.last_n_months):
            current_month = current_month.replace(day=1)

            yield current_month

            current_month = current_month - timedelta(days=1)


@workflow.defn(name="squash-person-overrides")
class SquashPersonOverridesWorkflow(PostHogWorkflow):
    """Workflow to squash outstanding person overrides into events.

    Squashing refers to the process of updating the person_id associated with an event
    to match the new id assigned via a person override. This process must be done
    regularly to control the size of the person_overrides table.

    For example, let's imagine the initial state of tables as:

    posthog_personoverridesmapping

    | id      | uuid                                   |
    | ------- + -------------------------------------- |
    | 1       | '179bed4d-0cf9-49a5-8826-b4c36348fae4' |
    | 2       | 'ced21432-7528-4045-bc22-855cbe69a6c1' |

    posthog_personoverride

    | old_person_id | override_person_id |
    | ------------- + ------------------ |
    | 1             | 2                  |

    The activity select_persons_to_delete will select the uuid with id 1 as safe to delete
    as its the only old_person_id at the time of starting.

    While executing this job, a new override (2->3) may be inserted, leaving both tables as:

    posthog_personoverridesmapping

    | id      | uuid                                   |
    | ------- + -------------------------------------- |
    | 1       | '179bed4d-0cf9-49a5-8826-b4c36348fae4' |
    | 2       | 'ced21432-7528-4045-bc22-855cbe69a6c1' |
    | 3       | 'b57de46b-55ad-4126-9a92-966fac570ec4' |

    posthog_personoverride

    | old_person_id | override_person_id |
    | ------------- + ------------------ |
    | 1             | 3                  |
    | 2             | 3                  |

    Upon executing the squash_events_partition events with person_id 1 or 2 will be correctly
    updated to reference person_id 3.

    At the end, we'll cleanup the tables by deleting the old_person_ids we deemed safe to do
    so (1) from both tables:

    posthog_personoverridesmapping

    | id      | uuid                                   |
    | ------- + -------------------------------------- |
    | 2       | 'ced21432-7528-4045-bc22-855cbe69a6c1' |
    | 3       | 'b57de46b-55ad-4126-9a92-966fac570ec4' |

    posthog_personoverride

    | old_person_id | override_person_id |
    | ------------- + ------------------ |
    | 2             | 3                  |

    Any overrides that arrived during the job will be left there for the next job run to clean
    up. These will be a no-op for the next job run as the override will already have been applied.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SquashPersonOverridesInputs:
        """Parse inputs from the management command CLI.

        We assume only one JSON serialized input and go from there.
        """
        if not inputs:
            return SquashPersonOverridesInputs()

        loaded = json.loads(inputs[0])
        return SquashPersonOverridesInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SquashPersonOverridesInputs):
        """Workflow implementation to squash person overrides into events table."""
        workflow.logger.info("Starting squash workflow")
        workflow.logger.debug("%s", json.dumps(asdict(inputs)))

        retry_policy = RetryPolicy(maximum_attempts=3)
        query_inputs = QueryInputs(
            dictionary_name=inputs.dictionary_name,
            team_ids=inputs.team_ids,
            dry_run=inputs.dry_run,
        )

        async with person_overrides_dictionary(
            workflow,
            query_inputs,
            # Let's be kinder to ClickHouse when running ON CLUSTER queries.
            # We use a higher initial_interval for retries so that we let ClickHouse finish up.
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
        ) as latest_created_at:
            query_inputs._latest_created_at = latest_created_at
            query_inputs.partition_ids = list(inputs.iter_partition_ids())

            persons_to_delete = await workflow.execute_activity(
                select_persons_to_delete,
                query_inputs,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=retry_policy,
            )

            query_inputs.person_overrides_to_delete = persons_to_delete

            await workflow.execute_activity(
                squash_events_partition,
                query_inputs,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            workflow.logger.info("Squash finished for all requested partitions, running clean up activities")

            if not persons_to_delete:
                workflow.logger.info("No overrides to delete were found, workflow done")
                return

            await workflow.execute_activity(
                delete_squashed_person_overrides_from_clickhouse,
                query_inputs,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            await workflow.execute_activity(
                delete_squashed_person_overrides_from_postgres,
                query_inputs,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

        workflow.logger.info("Done 🎉")
