"""Give persons the `$initial_geoip_*` properties that events ingested without GeoIP did not set.

A person whose first events were ingested without GeoIP has no `$initial_geoip_*` properties, or has
the ones a later event set once. This job reads the persons of the events a geoip_backfill_staging_job
run staged, and sends the `$set_once` of each person's earliest staged event to personhog. The leader
resolves set-once under the person lock, so a key the person already holds keeps its value: the job
never overwrites a value, even one a later event set.

The write goes through `UpdatePersonProperties` on the personhog leader. Where the leader path is not
configured, the first write fails the job. A dry run only reads, so it works without the leader.
"""

import json
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.dags.common import dagster_tags
from posthog.dags.geoip_backfill import OWNER_TAG, GeoipStagingTable, tagged
from posthog.dags.geoip_enrichment import GEOIP_KEYS, INITIAL_GEOIP_PREFIX
from posthog.dataclasses import frozen
from posthog.personhog_client.client import require_personhog_client
from posthog.personhog_client.proto import GetPersonsByUuidsRequest, UpdatePersonPropertiesRequest

INITIAL_GEOIP_KEYS: tuple[str, ...] = tuple(f"{INITIAL_GEOIP_PREFIX}{key}" for key in GEOIP_KEYS)

# GetPersonsByUuids takes at most this many UUIDs per request.
_PERSONS_PER_READ = 250


class GeoipPersonsConfig(dagster.Config):
    staging_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_staging_job run to read.")
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Repair only these teams. Leave empty to repair every staged team."
    )
    dry_run: bool = pydantic.Field(default=True, description="Report what the job would write, and write nothing.")
    team_chunk_size: int = pydantic.Field(default=50, ge=1, description="Teams per staging read.")
    max_writes_per_second: float = pydantic.Field(
        default=200.0, gt=0, description="Upper bound on personhog writes, to protect the leader."
    )


@frozen
class FirstStagedEvent:
    """The `$set_once` GeoIP keys of a person's earliest staged event."""

    team_id: int
    person_uuid: str
    timestamp: datetime
    initial_geoip: dict[str, Any]


@frozen
class PersonRepair:
    """What the job does for one person: write the keys it lacks, or report one whose value differs."""

    team_id: int
    person_id: int
    set_once: dict[str, Any]
    missing_keys: tuple[str, ...]
    differs: bool


@frozen
class PersonRepairTotals:
    persons: int
    not_found: int
    to_write: int
    already_set: int
    differs: int
    written: int


def first_staged_events(rows: Sequence[tuple[int, Any, datetime, str]]) -> dict[tuple[int, str], FirstStagedEvent]:
    """Keep each person's earliest event across the rows that every shard returned.

    A person's distinct IDs can live on different shards, so each shard returns its own earliest event.
    """
    first: dict[tuple[int, str], FirstStagedEvent] = {}
    for team_id, person_uuid, timestamp, set_once in rows:
        key = (team_id, str(person_uuid))
        if key in first and first[key].timestamp <= timestamp:
            continue
        values = _json_object(set_once)
        first[key] = FirstStagedEvent(
            team_id=team_id,
            person_uuid=str(person_uuid),
            timestamp=timestamp,
            initial_geoip={name: values.get(name) for name in INITIAL_GEOIP_KEYS},
        )
    return first


def plan_person_repair(event: FirstStagedEvent, person_id: int, properties: Mapping[str, Any]) -> PersonRepair:
    missing_keys = tuple(name for name in event.initial_geoip if name not in properties)
    present_country = properties.get(f"{INITIAL_GEOIP_PREFIX}country_code")
    staged_country = event.initial_geoip.get(f"{INITIAL_GEOIP_PREFIX}country_code")
    differs = f"{INITIAL_GEOIP_PREFIX}country_code" in properties and present_country != staged_country
    return PersonRepair(
        team_id=event.team_id,
        person_id=person_id,
        set_once=event.initial_geoip,
        missing_keys=missing_keys,
        differs=differs,
    )


def _json_object(value: str | bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def staged_first_events_query(table: GeoipStagingTable) -> str:
    # A personless event carries no person, so its `$set_once` never reached one.
    return f"""
        SELECT team_id, person_id, min(timestamp), argMin(JSONExtractRaw(properties, '$set_once'), timestamp)
        FROM {table.qualified_name} FINAL
        WHERE team_id IN %(team_ids)s AND person_mode = 'full'
        GROUP BY team_id, person_id
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
        totals = PersonRepairTotals(persons=0, not_found=0, to_write=0, already_set=0, differs=0, written=0)
        for chunk in _chunks(team_ids, self.config.team_chunk_size):
            events = first_staged_events(self._read_first_events(tuple(chunk)))
            repairs, not_found = self._plan(client, list(events.values()))
            to_write = [repair for repair in repairs if repair.missing_keys]
            written = 0 if self.config.dry_run else self._write(client, to_write)
            totals = PersonRepairTotals(
                persons=totals.persons + len(events),
                not_found=totals.not_found + not_found,
                to_write=totals.to_write + len(to_write),
                already_set=totals.already_set + len(repairs) - len(to_write),
                differs=totals.differs + sum(repair.differs for repair in repairs),
                written=totals.written + written,
            )
            action = "would write" if self.config.dry_run else "wrote"
            self.log.info(f"{len(chunk)} team(s): {len(events)} person(s), {action} {len(to_write)}")
        return totals

    def _read_first_events(self, team_ids: tuple[int, ...]) -> list[tuple[int, Any, datetime, str]]:
        query = staged_first_events_query(self.table)

        def read(client: Client) -> list[tuple[int, Any, datetime, str]]:
            return client.execute(query, {"team_ids": team_ids})

        rows: list[tuple[int, Any, datetime, str]] = []
        for shard_rows in self.cluster.map_one_host_per_shard(tagged(self.query_tags, read)).result().values():
            rows.extend(shard_rows)
        return rows

    def _plan(self, client: Any, events: Sequence[FirstStagedEvent]) -> tuple[list[PersonRepair], int]:
        by_team: dict[int, list[FirstStagedEvent]] = {}
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
                    repairs.append(plan_person_repair(event, person.id, _json_object(person.properties)))
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
                    # All keys go to the leader, not only the ones the read found missing. The leader resolves
                    # set-once against its own state, so a key another write set since the read keeps its value.
                    set_once_properties=json.dumps(repair.set_once).encode(),
                )
            )
            written += int(response.updated)
            if (elapsed := time.monotonic() - started) < interval:
                time.sleep(interval - elapsed)
        return written


@dagster.op(tags=OWNER_TAG)
def repair_initial_geoip_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: GeoipPersonsConfig,
) -> None:
    """Set the missing `$initial_geoip_*` properties of the staged events' persons, once.

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
            "to_write": dagster.MetadataValue.int(totals.to_write),
            "already_set": dagster.MetadataValue.int(totals.already_set),
            "differs_left_unchanged": dagster.MetadataValue.int(totals.differs),
            "written": dagster.MetadataValue.int(totals.written),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


@dagster.job(tags=OWNER_TAG)
def geoip_backfill_persons_job() -> None:
    """Set the missing `$initial_geoip_*` person properties from a geoip_backfill_staging_job run.

    Defaults to a dry run. Safe to re-run: a set-once write changes nothing on a person that holds the key.
    """
    repair_initial_geoip_persons()
