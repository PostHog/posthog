from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

from dateutil.parser import isoparse
from psycopg.types.json import Jsonb

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.local_bootstrap.config import (
    BootstrapConfig,
    DiscoveredFile,
    Table,
    TableImportConfig,
    TablePlan,
    TableResult,
)
from posthog.local_bootstrap.source import iter_table_rows
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import PERSON_DISTINCT_ID_TABLE

ZERO_UUID = "00000000-0000-0000-0000-000000000000"
ZERO_DT = datetime(1970, 1, 1)

# Batch size for the persons-DB inserts (mirrors the prior bulk_create batch_size).
_PG_WRITE_BATCH = 1000

# Columns we write directly into sharded_events (mirrors INSERT_EVENT_SQL minus computed columns).
_EVENT_COLUMNS = [
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "person_id",
    "person_properties",
    "person_created_at",
    "group0_properties",
    "group1_properties",
    "group2_properties",
    "group3_properties",
    "group4_properties",
    "group0_created_at",
    "group1_created_at",
    "group2_created_at",
    "group3_created_at",
    "group4_created_at",
    "person_mode",
    "created_at",
    "_timestamp",
    "_offset",
]

_PERSON_COLUMNS = [
    "id",
    "created_at",
    "team_id",
    "properties",
    "is_identified",
    "_timestamp",
    "_offset",
    "is_deleted",
    "version",
    "last_seen_at",
]

_PERSON_DISTINCT_ID_COLUMNS = [
    "distinct_id",
    "person_id",
    "team_id",
    "is_deleted",
    "version",
    "_timestamp",
    "_offset",
    "_partition",
]


@dataclass
class Progress:
    """Optional progress callbacks. ``on_file`` fires before each file is read; ``on_rows`` fires
    after each batch with the running total for the table."""

    on_file: Callable[[Table, DiscoveredFile, int, int], None] | None = None
    on_rows: Callable[[Table, int], None] | None = None

    def file(self, table: Table, discovered: DiscoveredFile, index: int, total: int) -> None:
        if self.on_file is not None:
            self.on_file(table, discovered, index, total)

    def rows(self, table: Table, total: int) -> None:
        if self.on_rows is not None:
            self.on_rows(table, total)


@dataclass
class BootstrapReport:
    team_id: int
    project_name: str
    email: str
    created_user: bool
    results: list[TableResult] = field(default_factory=list)

    def rows_for(self, table: Table) -> int:
        return sum(r.rows_imported for r in self.results if r.table == table)


def _ch_tags(team_id: int) -> AbstractContextManager[None]:
    return tags_context(product=Product.GROWTH, feature=Feature.MANAGEMENT_COMMAND, team_id=team_id)


def _aware_utc(value: Any, default: datetime) -> datetime:
    if value is None:
        value = default
    if isinstance(value, int | float):
        # Batch-export persons store created_at as epoch seconds (uint32), not a parquet timestamp.
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        value = isoparse(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _naive_utc(value: Any, default: datetime) -> datetime:
    return _aware_utc(value, default).replace(tzinfo=None)


def ensure_project(config: BootstrapConfig) -> tuple[Team, User, bool]:
    """Create the local project. If the email already exists, attach a fresh org+team to that user;
    otherwise bootstrap a brand-new org, user (password from config), and team. Returns
    ``(team, user, created_user)``."""
    existing = User.objects.filter(email=config.email).first()
    if existing is None:
        _organization, team, user = User.objects.bootstrap(
            organization_name=config.project_name,
            email=config.email,
            password=config.password,
            team_fields={"name": config.project_name},
        )
        return team, user, True

    organization = Organization.objects.create(name=config.project_name)
    team = Team.objects.create_with_data(initiating_user=existing, organization=organization, name=config.project_name)
    existing.join(organization=organization, level=OrganizationMembership.Level.OWNER)
    return team, existing, False


def _event_row_to_ch(row: dict[str, Any], team_id: int, now: datetime) -> dict[str, Any]:
    return {
        "uuid": str(row.get("uuid") or uuid.uuid4()),
        "event": row.get("event") or "",
        "properties": row.get("properties") or "",
        "timestamp": _naive_utc(row.get("timestamp"), now),
        "team_id": team_id,
        "distinct_id": str(row.get("distinct_id") or ""),
        "elements_chain": row.get("elements_chain") or "",
        "person_id": str(row.get("person_id") or ZERO_UUID),
        "person_properties": row.get("person_properties") or "",
        "person_created_at": ZERO_DT,
        "group0_properties": "",
        "group1_properties": "",
        "group2_properties": "",
        "group3_properties": "",
        "group4_properties": "",
        "group0_created_at": ZERO_DT,
        "group1_created_at": ZERO_DT,
        "group2_created_at": ZERO_DT,
        "group3_created_at": ZERO_DT,
        "group4_created_at": ZERO_DT,
        "person_mode": "full",
        "created_at": _naive_utc(row.get("created_at"), now),
        "_timestamp": now,
        "_offset": 0,
    }


def _insert_events_batch(rows: list[dict[str, Any]], team_id: int) -> None:
    sql = f"INSERT INTO {EVENTS_DATA_TABLE()} ({', '.join(_EVENT_COLUMNS)}) VALUES"
    with _ch_tags(team_id):
        sync_execute(sql, rows)


def import_events(
    team: Team, config: TableImportConfig, files: list[DiscoveredFile], batch_size: int, progress: Progress
) -> TableResult:
    now = datetime.now(UTC).replace(tzinfo=None)
    total = 0
    batch: list[dict[str, Any]] = []

    def on_file_start(discovered: DiscoveredFile, index: int) -> None:
        progress.file("events", discovered, index, len(files))

    for row in iter_table_rows(config, files, batch_size, on_file_start=on_file_start):
        batch.append(_event_row_to_ch(row, team.id, now))
        if len(batch) >= batch_size:
            _insert_events_batch(batch, team.id)
            total += len(batch)
            batch = []
            progress.rows("events", total)

    if batch:
        _insert_events_batch(batch, team.id)
        total += len(batch)
        progress.rows("events", total)

    return TableResult(table="events", rows_imported=total)


@dataclass
class _PersonAccumulator:
    properties: str
    version: int
    created_at: datetime
    is_deleted: bool
    distinct_ids: dict[str, int]


def _accumulate_persons(
    config: TableImportConfig, files: list[DiscoveredFile], batch_size: int, progress: Progress
) -> dict[str, _PersonAccumulator]:
    """Collapse the denormalized (person, distinct_id) export rows into one entry per person.
    Persons must be deduped across the whole dump, so this holds them in memory — fine for the
    person-sized slice of a project, which is far smaller than the events table."""
    now = datetime.now(UTC)
    persons: dict[str, _PersonAccumulator] = {}
    read = 0

    def on_file_start(discovered: DiscoveredFile, index: int) -> None:
        progress.file("persons", discovered, index, len(files))

    for row in iter_table_rows(config, files, batch_size, on_file_start=on_file_start):
        read += 1
        person_id = str(row.get("person_id") or "")
        if not person_id or person_id == ZERO_UUID:
            continue
        is_deleted = bool(row.get("is_deleted"))
        version = int(row.get("person_version") or 0)
        entry = persons.get(person_id)
        if entry is None:
            entry = _PersonAccumulator(
                properties=row.get("properties") or "{}",
                version=version,
                created_at=_aware_utc(row.get("created_at"), now),
                is_deleted=is_deleted,
                distinct_ids={},
            )
            persons[person_id] = entry
        else:
            entry.version = max(entry.version, version)
            entry.is_deleted = entry.is_deleted or is_deleted

        distinct_id = row.get("distinct_id")
        if distinct_id:
            did_version = int(row.get("person_distinct_id_version") or 0)
            entry.distinct_ids[distinct_id] = max(entry.distinct_ids.get(distinct_id, 0), did_version)

        if read % batch_size == 0:
            progress.rows("persons", read)

    return persons


def _write_persons_to_postgres(team_id: int, persons: dict[str, _PersonAccumulator]) -> None:
    if not persons:
        return

    # (uuid, properties, version, created_at) per person. created_at is written directly here,
    # unlike the auto_now_add ORM path which had to restamp it after the fact.
    person_rows: list[tuple[uuid.UUID, Jsonb, int, datetime]] = []
    for person_id, entry in persons.items():
        try:
            properties = json.loads(entry.properties)
        except (json.JSONDecodeError, TypeError):
            properties = {}
        person_rows.append((uuid.UUID(person_id), Jsonb(properties), entry.version, entry.created_at))

    with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
        # Map each canonical UUID to its generated id so distinct IDs can reference person_id.
        id_by_uuid: dict[str, int] = {}
        for i in range(0, len(person_rows), _PG_WRITE_BATCH):
            person_batch = person_rows[i : i + _PG_WRITE_BATCH]
            person_placeholders = ", ".join(["(%s, %s, %s, %s, %s, true)"] * len(person_batch))
            person_params = [
                value
                for person_uuid, properties, version, created_at in person_batch
                for value in (team_id, person_uuid, properties, version, created_at)
            ]
            cursor.execute(
                f"INSERT INTO {settings.PERSON_TABLE_NAME} "
                f"(team_id, uuid, properties, version, created_at, is_identified) VALUES {person_placeholders} "
                "RETURNING id, uuid",
                person_params,
            )
            for person_pk, person_uuid in cursor.fetchall():
                id_by_uuid[str(person_uuid)] = person_pk

        distinct_rows: list[tuple[str, int, int, int]] = [
            (distinct_id, id_by_uuid[str(uuid.UUID(person_id))], team_id, version)
            for person_id, entry in persons.items()
            for distinct_id, version in entry.distinct_ids.items()
        ]
        for i in range(0, len(distinct_rows), _PG_WRITE_BATCH):
            distinct_batch = distinct_rows[i : i + _PG_WRITE_BATCH]
            distinct_placeholders = ", ".join(["(%s, %s, %s, %s)"] * len(distinct_batch))
            distinct_params = [value for row in distinct_batch for value in row]
            cursor.execute(
                f"INSERT INTO {PERSON_DISTINCT_ID_TABLE} (distinct_id, person_id, team_id, version) "
                f"VALUES {distinct_placeholders}",
                distinct_params,
            )


def _write_persons_to_clickhouse(team: Team, persons: dict[str, _PersonAccumulator]) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    person_rows: list[dict[str, Any]] = []
    distinct_rows: list[dict[str, Any]] = []
    for person_id, entry in persons.items():
        created_at = entry.created_at.replace(tzinfo=None)
        person_rows.append(
            {
                "id": person_id,
                "created_at": created_at,
                "team_id": team.id,
                "properties": entry.properties,
                "is_identified": 1,
                "_timestamp": now,
                "_offset": 0,
                "is_deleted": 0,
                "version": entry.version,
                "last_seen_at": created_at,
            }
        )
        for distinct_id, version in entry.distinct_ids.items():
            distinct_rows.append(
                {
                    "distinct_id": distinct_id,
                    "person_id": person_id,
                    "team_id": team.id,
                    "is_deleted": 0,
                    "version": version,
                    "_timestamp": now,
                    "_offset": 0,
                    "_partition": 0,
                }
            )

    with _ch_tags(team.id):
        if person_rows:
            sync_execute(f"INSERT INTO person ({', '.join(_PERSON_COLUMNS)}) VALUES", person_rows)
        if distinct_rows:
            sync_execute(
                f"INSERT INTO person_distinct_id2 ({', '.join(_PERSON_DISTINCT_ID_COLUMNS)}) VALUES", distinct_rows
            )


def import_persons(
    team: Team, config: TableImportConfig, files: list[DiscoveredFile], batch_size: int, progress: Progress
) -> TableResult:
    accumulated = _accumulate_persons(config, files, batch_size, progress)
    live = {pid: entry for pid, entry in accumulated.items() if not entry.is_deleted}

    _write_persons_to_postgres(team.id, live)
    _write_persons_to_clickhouse(team, live)

    distinct_ids = sum(len(entry.distinct_ids) for entry in live.values())
    progress.rows("persons", len(live))
    return TableResult(table="persons", rows_imported=len(live), distinct_ids_imported=distinct_ids)


def run_bootstrap(
    config: BootstrapConfig,
    plans: list[TablePlan],
    progress: Progress | None = None,
    team_id: int | None = None,
) -> BootstrapReport:
    config.validate(require_identity=team_id is None)
    progress = progress or Progress()

    if team_id is not None:
        team = Team.objects.get(id=team_id)
        created_user = False
        project_name = team.name
        email = config.email or ""
    else:
        team, _user, created_user = ensure_project(config)
        project_name = config.project_name
        email = config.email

    report = BootstrapReport(team_id=team.id, project_name=project_name, email=email, created_user=created_user)
    for plan in plans:
        if plan.config.table == "events":
            report.results.append(import_events(team, plan.config, plan.files, config.batch_size, progress))
        else:
            report.results.append(import_persons(team, plan.config, plan.files, config.batch_size, progress))

    return report
