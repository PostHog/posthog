import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol, cast
from uuid import UUID

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import EmbeddedClickHouseQuery, HogQLQueryExecutor

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import kill_switch_overrides
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person_group_membership.sql import PERSON_GROUP_MEMBERSHIP_TABLE
from posthog.models.team import Team
from posthog.redis import get_client as get_redis_client
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client

from products.customer_analytics.backend.facade.membership_snapshot_contracts import (
    MAX_CHECKPOINT_KEY_BYTES,
    MembershipSnapshotBatch,
    MembershipSnapshotCheckpoint,
    MembershipSnapshotInput,
    MembershipSnapshotStep,
)
from products.customer_analytics.backend.logic.membership_backfill import (
    QUERY_SETTINGS,
    MembershipBackfillService,
    MembershipRow,
    get_membership_group_type_index,
)
from products.data_modeling.backend.facade import api as data_modeling_api
from products.data_modeling.backend.facade.contracts import MaterializedQuerySnapshot

MAX_BATCH_BYTES = 8_000_000


class MembershipSnapshotRejectedError(ValueError):
    pass


def parse_snapshot_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise MembershipSnapshotRejectedError("Snapshot timestamps must retain datetime precision")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def prepare_membership_snapshot(input: MembershipSnapshotInput) -> MaterializedQuerySnapshot:
    team = Team.objects.get(id=input.team_id)
    if get_membership_group_type_index(team) != input.group_type_index:
        raise MembershipSnapshotRejectedError(
            "The configured account group type changed. Check the project configuration"
        )
    if (
        not input.dry_run
        and MembershipBackfillService().get_active_state(input.team_id, input.membership_version) is None
    ):
        raise MembershipSnapshotRejectedError(
            "Membership configuration changed or is disabled. Verify it before continuing"
        )
    snapshot = data_modeling_api.get_materialized_query_snapshot(
        input.team_id, UUID(input.source_view_id), UUID(input.source_job_id)
    )
    if snapshot.rows_materialized < input.expected_rows:
        raise MembershipSnapshotRejectedError("The source contains fewer rows than expected. Verify the snapshot")
    return snapshot


def get_snapshot_read_settings(
    settings: Mapping[str, object], *, ceilings: Mapping[str, int], timeout: int
) -> dict[str, str]:
    params = {
        key: str(int(value)) if isinstance(value, bool) else str(value)
        for key, value in settings.items()
        if value is not None
    }
    read_budget = int(params.get("max_bytes_to_read", "0"))
    read_cap = cast(int, QUERY_SETTINGS["max_bytes_to_read"])
    params["max_bytes_to_read"] = str(min(read_budget, read_cap) if read_budget > 0 else read_cap)
    params["max_execution_time"] = str(min(120, max(1, timeout)))
    params["timeout_overflow_mode"] = "throw"
    params["read_overflow_mode"] = "throw"
    params["readonly"] = "2"
    for key, ceiling in ceilings.items():
        existing = int(params.get(key, "0"))
        params[key] = str(min(existing, ceiling) if existing > 0 else ceiling)
    return params


class MembershipSnapshotBackend(Protocol):
    async def check_source(self) -> None: ...

    def stream_rows(self, checkpoint: MembershipSnapshotCheckpoint) -> AsyncGenerator[Mapping[str, object]]: ...

    async def write_rows(self, rows: Sequence[MembershipRow]) -> None: ...


class ClickHouseMembershipSnapshotBackend:
    def __init__(self, batch: MembershipSnapshotBatch, *, deadline: float, should_stop: Callable[[], bool]) -> None:
        self.batch = batch
        self.deadline = deadline
        self.writer = MembershipBackfillService(deadline=deadline, should_stop=should_stop)

    def validate_source(self) -> None:
        self.writer.check_attempt()
        if prepare_membership_snapshot(self.batch.input) != self.batch.snapshot:
            raise MembershipSnapshotRejectedError("The source snapshot changed. Verify it before resuming")
        self.writer.check_attempt()

    async def check_source(self) -> None:
        await database_sync_to_async(self.validate_source, thread_sensitive=False)()

    def prepare_query(self, checkpoint: MembershipSnapshotCheckpoint) -> EmbeddedClickHouseQuery:
        self.validate_source()
        input = self.batch.input
        after = (
            parse_expr(
                "(group_key, distinct_id) > ({group_key}, {distinct_id})",
                placeholders={
                    "group_key": ast.Constant(value=checkpoint.group_key),
                    "distinct_id": ast.Constant(value=checkpoint.distinct_id),
                },
            )
            if checkpoint.rows_read
            else ast.Constant(value=True)
        )
        query = parse_select(
            """SELECT project_id, group_type_index, group_key, distinct_id, first_seen, last_seen,
                      eligibility_status, checked_at
               FROM {source}
               WHERE eligibility_status = 'eligible' AND {after}
               ORDER BY group_key, distinct_id
               LIMIT {remaining}""",
            placeholders={
                "source": ast.Field(chain=[self.batch.snapshot.name]),
                "after": after,
                "remaining": ast.Constant(value=input.max_rows - checkpoint.rows_read),
            },
        )
        compiled = HogQLQueryExecutor(
            query=query,
            team=Team.objects.get(id=input.team_id),
            query_type="MembershipSnapshotBackfill",
            workload=Workload.OFFLINE,
            limit_context=None,
            settings=HogQLGlobalSettings(
                max_execution_time=120, timeout_overflow_mode="throw", read_overflow_mode="throw"
            ),
            modifiers=HogQLQueryModifiers(useMaterializedViews=True),
            refresh_stale_view_columns=False,
        ).generate_clickhouse_subquery_sql()
        database = compiled.context.database
        if (
            compiled.context.referenced_saved_query_ids != {input.source_view_id}
            or database is None
            or not isinstance(database.get_table([self.batch.snapshot.name]), S3Table)
        ):
            raise MembershipSnapshotRejectedError("The source did not resolve to the pinned materialization")
        self.validate_source()
        return compiled

    async def stream_rows(self, checkpoint: MembershipSnapshotCheckpoint) -> AsyncGenerator[Mapping[str, object]]:
        input = self.batch.input
        compiled = await database_sync_to_async(self.prepare_query, thread_sensitive=False)(checkpoint)
        with tags_context(
            product=Product.CUSTOMER_ANALYTICS,
            feature=Feature.QUERY,
            team_id=input.team_id,
            workload=Workload.OFFLINE.value,
        ):
            async with get_client(team_id=input.team_id, max_block_size=input.batch_size) as reader:
                reader.params.update(
                    get_snapshot_read_settings(
                        {**reader.params, **compiled.settings},
                        ceilings=kill_switch_overrides(input.team_id),
                        timeout=int(self.deadline - monotonic()),
                    )
                )
                async for block in reader.astream_query_as_arrow(
                    compiled.sql + " FORMAT ArrowStream", query_parameters=compiled.context.values
                ):
                    for offset in range(0, block.num_rows, input.batch_size):
                        for source in block.slice(offset, input.batch_size).to_pylist():
                            yield cast(Mapping[str, object], source)

    def insert_rows(self, rows: Sequence[MembershipRow]) -> None:
        self.validate_source()
        input = self.batch.input
        self.writer.query(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} "
            "(team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES",
            [
                (input.team_id, input.group_type_index, row.group_key, row.distinct_id, row.first_seen, row.last_seen)
                for row in rows
            ],
            team_id=input.team_id,
        )
        actual = self.writer.query(
            f"SELECT group_key, distinct_id, min(first_seen), max(last_seen) FROM {PERSON_GROUP_MEMBERSHIP_TABLE} "
            "WHERE team_id = %(team_id)s AND group_type_index = %(index)s "
            "AND (group_key, distinct_id) IN %(keys)s GROUP BY group_key, distinct_id",
            {
                "team_id": input.team_id,
                "index": input.group_type_index,
                "keys": [(row.group_key, row.distinct_id) for row in rows],
            },
            team_id=input.team_id,
        )
        bounds = {
            (row[0], row[1]): (parse_snapshot_datetime(row[2]), parse_snapshot_datetime(row[3])) for row in actual
        }
        for row in rows:
            stored = bounds.get((row.group_key, row.distinct_id))
            if stored is None or stored[0] > row.first_seen or stored[1] < row.last_seen:
                raise RuntimeError(
                    "Could not verify the inserted membership bounds. Inspect the destination before resuming"
                )

    async def write_rows(self, rows: Sequence[MembershipRow]) -> None:
        task = asyncio.create_task(database_sync_to_async(self.insert_rows, thread_sensitive=False)(rows))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled await cannot stop the INSERT thread, so retain the lease until it finishes.
            await task
            raise


class MembershipSnapshotLoader:
    def __init__(self, batch: MembershipSnapshotBatch, backend: MembershipSnapshotBackend, *, deadline: float) -> None:
        self.batch = batch
        self.backend = backend
        self.deadline = deadline

    def parse_row(self, source: Mapping[str, object]) -> MembershipRow:
        input = self.batch.input
        if type(source.get("project_id")) is not int or type(source.get("group_type_index")) is not int:
            raise MembershipSnapshotRejectedError("Snapshot project and group type must be integers")
        if source.get("project_id") != input.team_id or source.get("group_type_index") != input.group_type_index:
            raise MembershipSnapshotRejectedError("A snapshot row belongs to another project or account group type")
        if (
            source.get("eligibility_status") != "eligible"
            or parse_snapshot_datetime(source.get("checked_at")) != input.checked_at
        ):
            raise MembershipSnapshotRejectedError("A row does not belong to the approved eligibility snapshot")
        group_key, distinct_id = source.get("group_key"), source.get("distinct_id")
        if not isinstance(group_key, str) or not group_key or not isinstance(distinct_id, str) or not distinct_id:
            raise MembershipSnapshotRejectedError("Snapshot membership keys must be nonempty strings")
        if len(group_key.encode()) + len(distinct_id.encode()) > MAX_CHECKPOINT_KEY_BYTES:
            raise MembershipSnapshotRejectedError("Membership keys exceed the checkpoint byte limit")
        first_seen = parse_snapshot_datetime(source.get("first_seen"))
        last_seen = parse_snapshot_datetime(source.get("last_seen"))
        if first_seen > last_seen:
            raise MembershipSnapshotRejectedError("A snapshot row has reversed membership timestamps")
        return MembershipRow(group_key=group_key, distinct_id=distinct_id, first_seen=first_seen, last_seen=last_seen)

    async def flush(
        self, rows: Sequence[MembershipRow], checkpoint: MembershipSnapshotCheckpoint
    ) -> MembershipSnapshotCheckpoint:
        await self.backend.check_source()
        input = self.batch.input
        if not rows or checkpoint.rows_read + len(rows) > input.max_rows:
            raise MembershipSnapshotRejectedError("The batch exceeds the approved row limit")
        if monotonic() >= self.deadline:
            raise RuntimeError("Membership snapshot attempt expired")
        if not input.dry_run:
            await self.backend.write_rows(rows)
        return replace(
            checkpoint,
            rows_read=checkpoint.rows_read + len(rows),
            rows_written=checkpoint.rows_written + (0 if input.dry_run else len(rows)),
            batches=checkpoint.batches + 1,
            group_key=rows[-1].group_key,
            distinct_id=rows[-1].distinct_id,
        )

    def get_checkpoint(self) -> MembershipSnapshotCheckpoint:
        input = self.batch.input
        checkpoint = self.batch.checkpoint
        if checkpoint.rows_read > input.max_rows or checkpoint.rows_written != (
            0 if input.dry_run else checkpoint.rows_read
        ):
            raise MembershipSnapshotRejectedError("The checkpoint does not match this run's mode or row limit")
        return checkpoint

    async def run(self, on_checkpoint: Callable[[MembershipSnapshotCheckpoint], None]) -> MembershipSnapshotStep:
        input = self.batch.input
        checkpoint = self.get_checkpoint()
        await self.backend.check_source()
        if checkpoint.rows_read == input.max_rows:
            return MembershipSnapshotStep(checkpoint=checkpoint, completed=True)
        rows: list[MembershipRow] = []
        batch_bytes = 0
        last_key = (checkpoint.group_key, checkpoint.distinct_id)
        async with aclosing(self.backend.stream_rows(checkpoint)) as source_rows:
            async for source in source_rows:
                row = self.parse_row(source)
                key = (row.group_key, row.distinct_id)
                if key <= last_key:
                    raise MembershipSnapshotRejectedError("Snapshot membership keys are duplicated or out of order")
                row_bytes = len(row.group_key.encode()) + len(row.distinct_id.encode()) + 64
                if row_bytes > MAX_BATCH_BYTES:
                    raise MembershipSnapshotRejectedError("A membership row exceeds the batch byte limit")
                if rows and batch_bytes + row_bytes > MAX_BATCH_BYTES:
                    checkpoint = await self.flush(rows, checkpoint)
                    on_checkpoint(checkpoint)
                    rows, batch_bytes = [], 0
                rows.append(row)
                last_key = key
                batch_bytes += row_bytes
                if len(rows) == input.batch_size:
                    checkpoint = await self.flush(rows, checkpoint)
                    on_checkpoint(checkpoint)
                    rows, batch_bytes = [], 0
                    if self.deadline - monotonic() < 15:
                        return MembershipSnapshotStep(
                            checkpoint=checkpoint, completed=checkpoint.rows_read == input.max_rows
                        )
            if rows:
                checkpoint = await self.flush(rows, checkpoint)
                on_checkpoint(checkpoint)
        await self.backend.check_source()
        if checkpoint.rows_read != input.max_rows:
            raise MembershipSnapshotRejectedError(
                "The snapshot ended before the expected row count. Verify its contents"
            )
        return MembershipSnapshotStep(checkpoint=checkpoint, completed=True)


async def load_membership_snapshot(
    batch: MembershipSnapshotBatch,
    *,
    deadline: float,
    should_stop: Callable[[], bool],
    on_checkpoint: Callable[[MembershipSnapshotCheckpoint], None],
) -> MembershipSnapshotStep:
    lease = get_redis_client(socket_timeout=2, socket_connect_timeout=2).lock(
        f"customer_analytics:membership_backfill:{batch.input.team_id}",
        timeout=330,
        blocking_timeout=5,
        thread_local=False,
    )
    if not await database_sync_to_async(lease.acquire, thread_sensitive=False)():
        raise RuntimeError("Another membership backfill attempt is active")
    try:
        backend = ClickHouseMembershipSnapshotBackend(
            batch, deadline=deadline, should_stop=lambda: should_stop() or not lease.owned()
        )
        return await MembershipSnapshotLoader(batch, backend, deadline=deadline).run(on_checkpoint)
    finally:
        if await database_sync_to_async(lease.owned, thread_sensitive=False)():
            await database_sync_to_async(lease.release, thread_sensitive=False)()
