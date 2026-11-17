"""Give persons the GeoIP person properties that events ingested without GeoIP did not set.

A person whose first events were ingested without GeoIP has no `$initial_geoip_*` properties, or has
the ones a later event set once. This job reads the persons of the events a geoip_backfill_staging_job
run staged, and sends the `$set_once` of each person's earliest staged event to personhog. The leader
resolves set-once under the person lock, so a key the person already holds keeps its value: the job
never overwrites a value, even one a later event set.

With `repair_latest_geoip`, the job also sends the `$set` of each person's last staged event, but only
for a person that no event set `$geoip_*` for after that one. Such a person still holds the location of
an event from before the incident, or none at all. Right before the write, the job reads the person
again and leaves the `$set` out when its `$geoip_*` changed since the check. The write is a plain `$set`,
so an event that sets `$geoip_*` between that read and the write is still overwritten.

A person missing under the staged person UUID was deleted, or merged into another person since the
event. The job looks the event's distinct ID up, and gives the person that holds it now the `$set_once`
of the earliest staged event among its own and the merged ones. It sets no `$geoip_*` on such a person,
because the merged events no longer tell where it was last.

Every run logs each person it writes, or would write in a dry run, to a table of its own: the keys, the
values sent, and the values those keys held before. A rollback reads that table.

The write goes through `UpdatePersonProperties` on the personhog leader. A run that writes checks first
that the leader path is configured, and fails before it reads anything. A dry run only reads, so it
works without the leader. The job skips and counts a person the leader no longer has or cannot store
(NOT_FOUND, INVALID_ARGUMENT), and backs off and retries a partition handoff, a fenced person or a full
dirty index (FAILED_PRECONDITION, RESOURCE_EXHAUSTED).
"""

import json
import time
import uuid
import dataclasses
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from django.conf import settings

import grpc
import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.execute import ClickHouseExternalTable
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme
from posthog.dags.common import dagster_tags
from posthog.dags.common.shards import shard_workload, tagged
from posthog.dags.geoip_backfill import OWNER_TAG, PRODUCT, GeoipStagingTable, staged_team_ids
from posthog.dags.geoip_enrichment import GEOIP_KEYS, GEOIP_PREFIX, INITIAL_GEOIP_PREFIX
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.personhog_client.client import require_personhog_client
from posthog.personhog_client.proto import (
    CONSISTENCY_LEVEL_STRONG,
    GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByUuidsRequest,
    ReadOptions,
    UpdatePersonPropertiesRequest,
)

INITIAL_GEOIP_KEYS: tuple[str, ...] = tuple(f"{INITIAL_GEOIP_PREFIX}{key}" for key in GEOIP_KEYS)
LATEST_GEOIP_KEYS: tuple[str, ...] = tuple(f"{GEOIP_PREFIX}{key}" for key in GEOIP_KEYS)

# GetPersonsByUuids and GetPersonsByDistinctIdsInTeam take at most this many per request.
_PERSONS_PER_READ = 250

# The leader rejects these writes for good, so the job skips the person.
_SKIPPED_CODES = {grpc.StatusCode.NOT_FOUND: "skipped_not_found", grpc.StatusCode.INVALID_ARGUMENT: "skipped_invalid"}
# The leader rejects these writes for now: a partition handoff or a fenced person (FAILED_PRECONDITION),
# or a dirty index at capacity (RESOURCE_EXHAUSTED).
_RETRIED_CODES = frozenset({grpc.StatusCode.FAILED_PRECONDITION, grpc.StatusCode.RESOURCE_EXHAUSTED})

GIB = 1024**3


class GeoipPersonsConfig(dagster.Config):
    staging_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_staging_job run to read.")
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Repair only these teams. Leave empty to repair every staged team."
    )
    dry_run: bool = pydantic.Field(default=True, description="Report what the job would write, and write nothing.")
    repair_latest_geoip: bool = pydantic.Field(
        default=False,
        description=(
            "Also set `$geoip_*` from a person's last staged event, when no event set it for that person "
            "after that one."
        ),
    )
    max_event_age_days: int = pydantic.Field(
        default=7,
        ge=0,
        description="How far before the last staged event a later event's own timestamp may be.",
    )
    team_chunk_size: int = pydantic.Field(default=50, ge=1, description="Teams per staging read.")
    max_writes_per_second: float = pydantic.Field(
        default=200.0, gt=0, description="Upper bound on personhog writes, to protect the leader."
    )
    max_write_attempts: int = pydantic.Field(
        default=8, ge=1, description="Attempts per person while the leader rejects the write for now."
    )
    retry_backoff_seconds: float = pydantic.Field(
        default=1.0, ge=0, description="The first wait before a retry. Each retry doubles it, up to a minute."
    )
    max_execution_time_seconds: int = pydantic.Field(default=10 * 60, description="ClickHouse max_execution_time.")
    max_memory_usage_bytes: int = pydantic.Field(default=16 * GIB, description="ClickHouse max_memory_usage.")


@frozen
class StagedPersonEvents:
    """The GeoIP keys a person's staged events would have written to the person."""

    team_id: int
    person_uuid: str
    first_timestamp: datetime
    initial_geoip: dict[str, Any]
    last_written_at: datetime
    latest_geoip: dict[str, Any]
    distinct_id: str

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "StagedPersonEvents":
        """A row of staged_person_events_query."""
        team_id, person_uuid, first_timestamp, set_once, last_written_at, latest_set, distinct_id = row
        return cls(
            team_id=team_id,
            person_uuid=str(person_uuid),
            first_timestamp=first_timestamp,
            initial_geoip=_pick(_json_object(set_once), INITIAL_GEOIP_KEYS),
            last_written_at=last_written_at,
            latest_geoip=_pick(_json_object(latest_set), LATEST_GEOIP_KEYS),
            distinct_id=distinct_id,
        )


@frozen
class PersonRepair:
    """What the job sends for one person, and the values those keys held before."""

    team_id: int
    person_id: int
    person_uuid: str
    set_once: dict[str, Any]
    set: dict[str, Any]
    previous: dict[str, Any]
    initial_differs: bool
    # The person's `$geoip_*` keys when the plan read it, to see whether they changed before the write.
    latest_read: dict[str, Any]

    @property
    def writes(self) -> bool:
        return bool(self.set_once or self.set)


# What one run counts. `merged` and `not_found` are persons missing under the staged person UUID.
TOTALS = (
    "persons",
    "merged",
    "not_found",
    "initial_to_write",
    "latest_to_write",
    "initial_differs",
    "latest_changed_before_write",
    "written",
    "unchanged",
    "skipped_not_found",
    "skipped_invalid",
    "retried",
)


def staged_person_events(
    per_shard: Sequence[StagedPersonEvents],
) -> dict[tuple[int, str], StagedPersonEvents]:
    """Keep each person's earliest and last staged event across what every shard returned.

    A person's distinct IDs can live on different shards, so each shard returns its own earliest and last event.
    """
    merged: dict[tuple[int, str], StagedPersonEvents] = {}
    for shard_events in per_shard:
        key = (shard_events.team_id, shard_events.person_uuid)
        known = merged.get(key)
        if known is None:
            merged[key] = shard_events
            continue
        first = known if known.first_timestamp <= shard_events.first_timestamp else shard_events
        last = known if known.last_written_at >= shard_events.last_written_at else shard_events
        merged[key] = dataclasses.replace(first, last_written_at=last.last_written_at, latest_geoip=last.latest_geoip)
    return merged


def plan_person_repair(
    events: StagedPersonEvents, person_id: int, properties: Mapping[str, Any], *, repair_latest: bool
) -> PersonRepair:
    initial_missing = any(name not in properties for name in events.initial_geoip)
    latest_differs = repair_latest and any(
        name not in properties or properties[name] != value for name, value in events.latest_geoip.items()
    )
    country_key = f"{INITIAL_GEOIP_PREFIX}country_code"
    set_once = events.initial_geoip if initial_missing else {}
    set_properties = events.latest_geoip if latest_differs else {}
    return PersonRepair(
        team_id=events.team_id,
        person_id=person_id,
        person_uuid=events.person_uuid,
        # All keys go to the leader, not only the ones the read found missing. The leader resolves set-once
        # against its own state, so a key another write set since the read keeps its value.
        set_once=set_once,
        set=set_properties,
        previous={name: properties.get(name) for name in [*set_once, *set_properties] if name in properties},
        initial_differs=country_key in properties and properties[country_key] != events.initial_geoip.get(country_key),
        latest_read=_present(properties, LATEST_GEOIP_KEYS),
    )


@frozen
class GeoipPersonsLog:
    """The persons one run writes, on every data host, kept after the run for a rollback.

    A rollback restores `previous_properties` for the keys whose value still equals the one sent.
    """

    id: uuid.UUID

    @property
    def name(self) -> str:
        # Matches the "tmp_*" glob in posthog/clickhouse/hcl/exclude.hcl.
        return f"tmp_geoip_backfill_persons_{self.id.hex}"

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client) -> None:
        engine = MergeTreeEngine(self.name, replication_scheme=ReplicationScheme.REPLICATED)
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                person_id Int64,
                person_uuid UUID,
                set_once_properties String,
                set_properties String,
                previous_properties String,
                logged_at DateTime
            )
            ENGINE = {engine}
            ORDER BY (team_id, person_id)
            """
        )

    def insert(self, repairs: Sequence[PersonRepair], client: Client) -> None:
        logged_at = datetime.now(UTC)
        client.execute(
            f"""INSERT INTO {self.qualified_name}
            (team_id, person_id, person_uuid, set_once_properties, set_properties, previous_properties, logged_at)
            VALUES""",
            [
                (
                    repair.team_id,
                    repair.person_id,
                    uuid.UUID(repair.person_uuid),
                    json.dumps(repair.set_once),
                    json.dumps(repair.set),
                    json.dumps(repair.previous),
                    logged_at,
                )
                for repair in repairs
            ],
        )

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")


def _present(values: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    return {name: values[name] for name in names if name in values}


def _pick(values: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    return {name: values.get(name) for name in names}


def _json_object(value: str | bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def staged_person_events_query(table: GeoipStagingTable) -> str:
    # A personless event carries no person, so its `$set_once` and `$set` never reached one.
    return f"""
        SELECT
            team_id,
            person_id,
            min(timestamp),
            argMin(JSONExtractRaw(properties, '$set_once'), timestamp),
            max(original_written_at),
            argMax(JSONExtractRaw(properties, '$set'), original_written_at),
            any(distinct_id)
        FROM {table.qualified_name} FINAL
        WHERE team_id IN %(team_ids)s AND person_mode = 'full'
        GROUP BY team_id, person_id
    """


def later_geoip_query(table: GeoipStagingTable) -> str:
    """The staged persons that an event set `$geoip_*` for after their last staged event.

    Ingestion applies `$set` in write order, so such a person already holds a location newer than the
    staged one. The staged copies themselves carry `$set.$geoip_*` once resent, so they stay out.
    """
    return f"""
        SELECT DISTINCT e.team_id, e.person_id
        FROM {EVENTS_DATA_TABLE()} AS e
        INNER JOIN _staged_persons AS p ON e.team_id = p.team_id AND e.person_id = p.person_id
        WHERE e.team_id IN %(team_ids)s
            AND e.timestamp >= %(timestamp_floor)s
            AND e._timestamp > %(written_after)s
            AND e._timestamp > p.last_written_at
            AND JSONHas(e.properties, '$set', '$geoip_country_code')
            AND e.uuid NOT IN (SELECT uuid FROM {table.qualified_name} WHERE team_id IN %(team_ids)s)
    """


@frozen
class PersonsRepair:
    cluster: ClickhouseCluster
    client: Any
    table: GeoipStagingTable
    written_persons: GeoipPersonsLog
    config: GeoipPersonsConfig
    log: dagster.DagsterLogManager
    query_tags: DagsterTags

    def run(self, team_ids: Sequence[int]) -> Counter[str]:
        totals: Counter[str] = Counter()
        for chunk in _chunks(team_ids, self.config.team_chunk_size):
            totals.update(self._repair_chunk(tuple(chunk)))
        return totals

    def _repair_chunk(self, team_ids: tuple[int, ...]) -> Counter[str]:
        totals: Counter[str] = Counter()
        events = list(staged_person_events(self._read_staged(team_ids)).values())
        current = self._persons_with_later_geoip(team_ids, events) if self.config.repair_latest_geoip else set()
        repairs = self._plan(events, current, totals)
        to_write = [repair for repair in repairs if repair.writes]
        if to_write:
            # Logged before the writes, so a run that fails part way through still lists every person it wrote.
            self.cluster.any_host_by_role(
                tagged(self.query_tags, partial(self.written_persons.insert, to_write), product=PRODUCT), NodeRole.DATA
            ).result()
        if not self.config.dry_run:
            self._write(to_write, totals)
        action = "would write" if self.config.dry_run else "wrote"
        self.log.info(f"{len(team_ids)} team(s): {len(events)} person(s), {action} {len(to_write)}")
        totals["persons"] += len(events)
        totals["initial_to_write"] += sum(bool(repair.set_once) for repair in repairs)
        totals["latest_to_write"] += sum(bool(repair.set) for repair in repairs)
        totals["initial_differs"] += sum(repair.initial_differs for repair in repairs)
        return totals

    def _read_staged(self, team_ids: tuple[int, ...]) -> list[StagedPersonEvents]:
        query = staged_person_events_query(self.table)

        def read(client: Client) -> list[StagedPersonEvents]:
            return [StagedPersonEvents.from_row(row) for row in client.execute(query, {"team_ids": team_ids})]

        return self._on_every_shard(read)

    def _persons_with_later_geoip(
        self, team_ids: tuple[int, ...], events: Sequence[StagedPersonEvents]
    ) -> set[tuple[int, str]]:
        if not events:
            return set()
        written_after = min(event.last_written_at for event in events)
        args = {
            "team_ids": team_ids,
            "written_after": written_after,
            "timestamp_floor": written_after - timedelta(days=self.config.max_event_age_days),
        }
        # A person's later events can sit on any shard, so every shard gets the whole chunk's persons.
        staged_persons: ClickHouseExternalTable = {
            "name": "_staged_persons",
            "structure": [("team_id", "Int64"), ("person_id", "UUID"), ("last_written_at", "DateTime")],
            "data": [
                {"team_id": event.team_id, "person_id": event.person_uuid, "last_written_at": event.last_written_at}
                for event in events
            ],
        }
        query = later_geoip_query(self.table)
        workload, _ = shard_workload()
        query_settings = {
            "max_execution_time": self.config.max_execution_time_seconds,
            "max_memory_usage": self.config.max_memory_usage_bytes,
        }

        def read(client: Client) -> list[tuple[int, Any]]:
            return sync_execute(
                query,
                args,
                settings=query_settings,
                workload=workload,
                sync_client=client,
                flush=False,
                external_tables=[staged_persons],
            )

        return {(team_id, str(person_uuid)) for team_id, person_uuid in self._on_every_shard(read)}

    def _on_every_shard(self, fn: Callable[[Client], list[Any]]) -> list[Any]:
        workload, node_role = shard_workload()
        per_shard = self.cluster.map_any_host_in_shards_by_role(
            {shard_num: tagged(self.query_tags, fn, product=PRODUCT) for shard_num in self.cluster.shards},
            workload=workload,
            node_role=node_role,
        ).result()
        return [row for rows in per_shard.values() for row in rows]

    def _plan(
        self, events: Sequence[StagedPersonEvents], later_geoip: set[tuple[int, str]], totals: Counter[str]
    ) -> list[PersonRepair]:
        by_team: dict[int, list[StagedPersonEvents]] = {}
        for event in events:
            by_team.setdefault(event.team_id, []).append(event)
        repairs: list[PersonRepair] = []
        for team_id, team_events in by_team.items():
            # Each current person with the staged events that belong to it now.
            current: dict[str, tuple[Any, list[StagedPersonEvents]]] = {}
            missing: list[StagedPersonEvents] = []
            for batch in _chunks(team_events, _PERSONS_PER_READ):
                persons = self._persons_by_uuid(team_id, [event.person_uuid for event in batch])
                for event in batch:
                    person = persons.get(event.person_uuid)
                    if person is None:
                        missing.append(event)
                    else:
                        current.setdefault(person.uuid, (person, []))[1].append(event)
            merged_into: set[str] = set()
            for event, person in self._merged_persons(team_id, missing, totals):
                current.setdefault(person.uuid, (person, []))[1].append(event)
                merged_into.add(person.uuid)
            for person_uuid, (person, person_events) in current.items():
                earliest = min(person_events, key=lambda event: event.first_timestamp)
                # A person that absorbed another one also holds that person's events, so the staged `$set`
                # no longer tells where it was last.
                repair_latest = (
                    self.config.repair_latest_geoip
                    and person_uuid not in merged_into
                    and (team_id, person_uuid) not in later_geoip
                )
                repairs.append(
                    plan_person_repair(
                        dataclasses.replace(earliest, person_uuid=person_uuid),
                        person.id,
                        _json_object(person.properties),
                        repair_latest=repair_latest,
                    )
                )
        return repairs

    def _persons_by_uuid(self, team_id: int, uuids: Sequence[str], *, strong: bool = False) -> dict[str, Any]:
        request = GetPersonsByUuidsRequest(team_id=team_id, uuids=list(uuids))
        if strong:
            request.read_options.CopyFrom(ReadOptions(consistency=CONSISTENCY_LEVEL_STRONG))
        return {person.uuid: person for person in self.client.get_persons_by_uuids(request).persons}

    def _merged_persons(
        self, team_id: int, missing: Sequence[StagedPersonEvents], totals: Counter[str]
    ) -> list[tuple[StagedPersonEvents, Any]]:
        """The person that holds each missing person's distinct ID now. One that no person holds was deleted."""
        merged: list[tuple[StagedPersonEvents, Any]] = []
        for batch in _chunks(missing, _PERSONS_PER_READ):
            response = self.client.get_persons_by_distinct_ids_in_team(
                GetPersonsByDistinctIdsInTeamRequest(
                    team_id=team_id, distinct_ids=[event.distinct_id for event in batch]
                )
            )
            holders = {result.distinct_id: result.person for result in response.results if result.HasField("person")}
            for event in batch:
                if event.distinct_id in holders:
                    merged.append((event, holders[event.distinct_id]))
                else:
                    totals["not_found"] += 1
        totals["merged"] += len(merged)
        return merged

    def _write(self, repairs: Sequence[PersonRepair], totals: Counter[str]) -> None:
        interval = 1.0 / self.config.max_writes_per_second
        for repair in repairs:
            started = time.monotonic()
            if repair.set:
                repair = self._without_latest_if_changed(repair, totals)
            if repair.writes:
                totals[self._write_person(repair, totals)] += 1
            if (elapsed := time.monotonic() - started) < interval:
                time.sleep(interval - elapsed)

    def _without_latest_if_changed(self, repair: PersonRepair, totals: Counter[str]) -> PersonRepair:
        """The repair without its `$set` when the person's `$geoip_*` changed since the plan read it."""
        person = self._persons_by_uuid(repair.team_id, [repair.person_uuid], strong=True).get(repair.person_uuid)
        if person is not None and _present(_json_object(person.properties), LATEST_GEOIP_KEYS) == repair.latest_read:
            return repair
        totals["latest_changed_before_write"] += 1
        return dataclasses.replace(repair, set={})

    def _write_person(self, repair: PersonRepair, totals: Counter[str]) -> str:
        """Write one person, and return the outcome it counts under."""
        request = UpdatePersonPropertiesRequest(
            team_id=repair.team_id,
            person_id=repair.person_id,
            event_name="$set",
            set_once_properties=json.dumps(repair.set_once).encode() if repair.set_once else b"",
            set_properties=json.dumps(repair.set).encode() if repair.set else b"",
            # `$geoip_*` keys other than the country are filtered: a change to them alone answers
            # updated=false and writes nothing, unless forced.
            force_update=True,
        )
        backoff = self.config.retry_backoff_seconds
        for attempt in range(1, self.config.max_write_attempts + 1):
            try:
                response = self.client.update_person_properties(request)
            except grpc.RpcError as error:
                code = error.code()
                if code in _SKIPPED_CODES:
                    self.log.warning(f"Skipped person {repair.person_uuid} of team {repair.team_id}: {code.name}")
                    return _SKIPPED_CODES[code]
                if code not in _RETRIED_CODES or attempt == self.config.max_write_attempts:
                    raise
                totals["retried"] += 1
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            return "written" if response.updated else "unchanged"
        raise AssertionError("unreachable")


@dagster.op(tags=OWNER_TAG)
def repair_geoip_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: GeoipPersonsConfig,
) -> None:
    """Set the missing `$initial_geoip_*` properties of the staged events' persons, and optionally `$geoip_*`.

    Persons whose `$initial_geoip_country_code` differs from their first staged event are only counted.
    """
    client = require_personhog_client()
    if not config.dry_run and not client.lifecycle.configured:
        raise dagster.Failure(
            description="The personhog leader path is not configured (PERSONHOG_LIFECYCLE_ADDR), so no write "
            "can go through. Run a dry run, or run where the leader path is configured."
        )
    table = GeoipStagingTable(id=uuid.UUID(config.staging_run_id))
    team_ids = staged_team_ids(cluster, table, config.team_ids)
    written_persons = GeoipPersonsLog(id=uuid.UUID(context.run_id))
    cluster.map_hosts_by_role(written_persons.create, NodeRole.DATA).result()
    totals = PersonsRepair(
        cluster=cluster,
        client=client,
        table=table,
        written_persons=written_persons,
        config=config,
        log=context.log,
        query_tags=dagster_tags(context),
    ).run(team_ids)
    context.log.info(f"{written_persons.qualified_name} lists the persons this run wrote or would write")
    context.add_output_metadata(
        {
            "written_persons_table": dagster.MetadataValue.text(written_persons.qualified_name),
            "teams": dagster.MetadataValue.int(len(team_ids)),
            **{name: dagster.MetadataValue.int(totals[name]) for name in TOTALS},
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


@dagster.job(tags=OWNER_TAG)
def geoip_backfill_persons_job() -> None:
    """Set the missing GeoIP person properties from a geoip_backfill_staging_job run.

    Defaults to a dry run. Safe to re-run: a set-once write changes nothing on a person that holds the key,
    and a `$geoip_*` write is skipped for a person that already holds the staged values.
    """
    repair_geoip_persons()


class PersonsRunConfig(dagster.Config):
    persons_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_persons_job run.")


@dagster.op(tags=OWNER_TAG)
def drop_written_persons(cluster: dagster.ResourceParam[ClickhouseCluster], config: PersonsRunConfig) -> None:
    cluster.map_hosts_by_role(GeoipPersonsLog(id=uuid.UUID(config.persons_run_id)).drop, NodeRole.DATA).result()


@dagster.job(tags=OWNER_TAG)
def cleanup_geoip_backfill_persons() -> None:
    """Drop the written-persons table of a geoip_backfill_persons_job run, once a rollback is ruled out."""
    drop_written_persons()
