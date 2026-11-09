"""Give persons the GeoIP person properties that events ingested without GeoIP did not set.

A person whose first events were ingested without GeoIP has no `$initial_geoip_*` properties, or has
the ones a later event set once. This job reads the persons of the events a geoip_backfill_staging_job
run staged, and sends the `$set_once` of each person's earliest staged event to personhog. The leader
resolves set-once under the person lock, so a key the person already holds keeps its value: the job
never overwrites a value, even one a later event set.

With `repair_latest_geoip`, the job also sends the `$set` of each person's last staged event, but only
for a person that no event set `$geoip_*` for after that one. Such a person still holds the location of
an event from before the incident, or none at all. This write is a plain `$set`, so an event that sets
`$geoip_*` between the job's check and its write is overwritten with the older location.

The write goes through `UpdatePersonProperties` on the personhog leader. Where the leader path is not
configured, the first write fails the job. A dry run only reads, so it works without the leader.
"""

import json
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.execute import ClickHouseExternalTable
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.dags.common import dagster_tags
from posthog.dags.flag_evaluations_backfill import shard_workload
from posthog.dags.geoip_backfill import OWNER_TAG, GeoipStagingTable, tagged
from posthog.dags.geoip_enrichment import GEOIP_KEYS, GEOIP_PREFIX, INITIAL_GEOIP_PREFIX
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.personhog_client.client import require_personhog_client
from posthog.personhog_client.proto import GetPersonsByUuidsRequest, UpdatePersonPropertiesRequest

INITIAL_GEOIP_KEYS: tuple[str, ...] = tuple(f"{INITIAL_GEOIP_PREFIX}{key}" for key in GEOIP_KEYS)
LATEST_GEOIP_KEYS: tuple[str, ...] = tuple(f"{GEOIP_PREFIX}{key}" for key in GEOIP_KEYS)

# GetPersonsByUuids takes at most this many UUIDs per request.
_PERSONS_PER_READ = 250

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

    @property
    def writes(self) -> bool:
        return bool(self.set_once or self.set)


@frozen
class PersonRepairTotals:
    persons: int
    not_found: int
    initial_to_write: int
    latest_to_write: int
    initial_differs: int
    written: int

    def __add__(self, other: "PersonRepairTotals") -> "PersonRepairTotals":
        return PersonRepairTotals(
            persons=self.persons + other.persons,
            not_found=self.not_found + other.not_found,
            initial_to_write=self.initial_to_write + other.initial_to_write,
            latest_to_write=self.latest_to_write + other.latest_to_write,
            initial_differs=self.initial_differs + other.initial_differs,
            written=self.written + other.written,
        )


EMPTY_TOTALS = PersonRepairTotals(
    persons=0, not_found=0, initial_to_write=0, latest_to_write=0, initial_differs=0, written=0
)


def staged_person_events(
    rows: Sequence[tuple[int, Any, datetime, str, datetime, str]],
) -> dict[tuple[int, str], StagedPersonEvents]:
    """Keep each person's earliest and last staged event across the rows that every shard returned.

    A person's distinct IDs can live on different shards, so each shard returns its own earliest and last event.
    """
    merged: dict[tuple[int, str], StagedPersonEvents] = {}
    for team_id, person_uuid, first_timestamp, set_once, last_written_at, latest_set in rows:
        key = (team_id, str(person_uuid))
        shard_events = StagedPersonEvents(
            team_id=team_id,
            person_uuid=str(person_uuid),
            first_timestamp=first_timestamp,
            initial_geoip=_pick(_json_object(set_once), INITIAL_GEOIP_KEYS),
            last_written_at=last_written_at,
            latest_geoip=_pick(_json_object(latest_set), LATEST_GEOIP_KEYS),
        )
        known = merged.get(key)
        if known is None:
            merged[key] = shard_events
            continue
        first = known if known.first_timestamp <= first_timestamp else shard_events
        last = known if known.last_written_at >= last_written_at else shard_events
        merged[key] = StagedPersonEvents(
            team_id=team_id,
            person_uuid=str(person_uuid),
            first_timestamp=first.first_timestamp,
            initial_geoip=first.initial_geoip,
            last_written_at=last.last_written_at,
            latest_geoip=last.latest_geoip,
        )
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
    )


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
            argMax(JSONExtractRaw(properties, '$set'), original_written_at)
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
    table: GeoipStagingTable
    config: GeoipPersonsConfig
    log: dagster.DagsterLogManager
    query_tags: DagsterTags

    def run(self, team_ids: Sequence[int]) -> PersonRepairTotals:
        client = require_personhog_client()
        totals = EMPTY_TOTALS
        for chunk in _chunks(team_ids, self.config.team_chunk_size):
            totals += self._repair_chunk(client, tuple(chunk))
        return totals

    def _repair_chunk(self, client: Any, team_ids: tuple[int, ...]) -> PersonRepairTotals:
        events = list(staged_person_events(self._read_staged(team_ids)).values())
        current = self._persons_with_later_geoip(team_ids, events) if self.config.repair_latest_geoip else set()
        repairs, not_found = self._plan(client, events, current)
        to_write = [repair for repair in repairs if repair.writes]
        written = 0 if self.config.dry_run else self._write(client, to_write)
        action = "would write" if self.config.dry_run else "wrote"
        self.log.info(f"{len(team_ids)} team(s): {len(events)} person(s), {action} {len(to_write)}")
        return PersonRepairTotals(
            persons=len(events),
            not_found=not_found,
            initial_to_write=sum(bool(repair.set_once) for repair in repairs),
            latest_to_write=sum(bool(repair.set) for repair in repairs),
            initial_differs=sum(repair.initial_differs for repair in repairs),
            written=written,
        )

    def _read_staged(self, team_ids: tuple[int, ...]) -> list[tuple[int, Any, datetime, str, datetime, str]]:
        query = staged_person_events_query(self.table)

        def read(client: Client) -> list[tuple[int, Any, datetime, str, datetime, str]]:
            return client.execute(query, {"team_ids": team_ids})

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
        settings = {
            "max_execution_time": self.config.max_execution_time_seconds,
            "max_memory_usage": self.config.max_memory_usage_bytes,
        }

        def read(client: Client) -> list[tuple[int, Any]]:
            return sync_execute(
                query,
                args,
                settings=settings,
                workload=workload,
                sync_client=client,
                flush=False,
                external_tables=[staged_persons],
            )

        return {(team_id, str(person_uuid)) for team_id, person_uuid in self._on_every_shard(read)}

    def _on_every_shard(self, fn: Callable[[Client], list[Any]]) -> list[Any]:
        rows: list[Any] = []
        for shard_rows in self.cluster.map_one_host_per_shard(tagged(self.query_tags, fn)).result().values():
            rows.extend(shard_rows)
        return rows

    def _plan(
        self, client: Any, events: Sequence[StagedPersonEvents], later_geoip: set[tuple[int, str]]
    ) -> tuple[list[PersonRepair], int]:
        by_team: dict[int, list[StagedPersonEvents]] = {}
        for event in events:
            by_team.setdefault(event.team_id, []).append(event)
        repairs: list[PersonRepair] = []
        not_found = 0
        for team_id, team_events in by_team.items():
            for batch in _chunks(team_events, _PERSONS_PER_READ):
                response = client.get_persons_by_uuids(
                    GetPersonsByUuidsRequest(team_id=team_id, uuids=[event.person_uuid for event in batch])
                )
                persons = {person.uuid: person for person in response.persons}
                for event in batch:
                    person = persons.get(event.person_uuid)
                    if person is None:
                        not_found += 1
                        continue
                    repair_latest = self.config.repair_latest_geoip and (team_id, event.person_uuid) not in later_geoip
                    repairs.append(
                        plan_person_repair(
                            event, person.id, _json_object(person.properties), repair_latest=repair_latest
                        )
                    )
        return repairs, not_found

    def _write(self, client: Any, repairs: Sequence[PersonRepair]) -> int:
        interval = 1.0 / self.config.max_writes_per_second
        written = 0
        for repair in repairs:
            started = time.monotonic()
            response = client.update_person_properties(
                UpdatePersonPropertiesRequest(
                    team_id=repair.team_id,
                    person_id=repair.person_id,
                    event_name="$set",
                    set_once_properties=json.dumps(repair.set_once).encode() if repair.set_once else b"",
                    set_properties=json.dumps(repair.set).encode() if repair.set else b"",
                )
            )
            written += int(response.updated)
            if (elapsed := time.monotonic() - started) < interval:
                time.sleep(interval - elapsed)
        return written


@dagster.op(tags=OWNER_TAG)
def repair_geoip_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: GeoipPersonsConfig,
) -> None:
    """Set the missing `$initial_geoip_*` properties of the staged events' persons, and optionally `$geoip_*`.

    Persons whose `$initial_geoip_country_code` differs from their first staged event are only counted.
    """
    table = GeoipStagingTable(id=uuid.UUID(config.staging_run_id))
    if not cluster.any_host_by_role(table.exists, NodeRole.DATA).result():
        raise dagster.Failure(description=f"{table.qualified_name} does not exist.")

    def staged_teams(client: Client) -> list[tuple[int]]:
        return client.execute(f"SELECT DISTINCT team_id FROM {table.qualified_name}")

    team_ids = {
        team_id for rows in cluster.map_one_host_per_shard(staged_teams).result().values() for (team_id,) in rows
    }
    if config.team_ids:
        team_ids &= set(config.team_ids)
    totals = PersonsRepair(
        cluster=cluster, table=table, config=config, log=context.log, query_tags=dagster_tags(context)
    ).run(sorted(team_ids))
    context.add_output_metadata(
        {
            "teams": dagster.MetadataValue.int(len(team_ids)),
            "persons": dagster.MetadataValue.int(totals.persons),
            "not_found": dagster.MetadataValue.int(totals.not_found),
            "initial_geoip_to_write": dagster.MetadataValue.int(totals.initial_to_write),
            "latest_geoip_to_write": dagster.MetadataValue.int(totals.latest_to_write),
            "initial_geoip_differs_left_unchanged": dagster.MetadataValue.int(totals.initial_differs),
            "written": dagster.MetadataValue.int(totals.written),
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
