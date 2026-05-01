"""Temporal Schedule helpers for ManagedWarehousePromotedTable rows."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings

import temporalio
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    a_create_schedule,
    a_delete_schedule,
    a_trigger_schedule,
    a_update_schedule,
    create_schedule,
    delete_schedule,
    schedule_exists,
    trigger_schedule,
    update_schedule,
)
from posthog.temporal.ducklake.promote_table_workflow import PromoteTableInputs

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ManagedWarehousePromotedTable


def _build_schedule(promoted_table: ManagedWarehousePromotedTable) -> Schedule:
    inputs = PromoteTableInputs(
        team_id=promoted_table.team_id,
        promoted_table_id=str(promoted_table.id),
    )

    interval = promoted_table.sync_frequency_interval or timedelta(hours=1)

    action = ScheduleActionStartWorkflow(
        "ducklake-promote-table",
        asdict(inputs),
        id=promoted_table.schedule_id,
        task_queue=str(settings.DUCKLAKE_TASK_QUEUE),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=120),
            maximum_attempts=2,
        ),
    )

    spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)])

    return Schedule(
        action=action,
        spec=spec,
        state=ScheduleState(
            note=f"Managed warehouse promoted table {promoted_table.id}",
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def sync_promote_table_schedule(
    promoted_table: ManagedWarehousePromotedTable,
    *,
    create: bool = False,
    trigger_immediately: bool = False,
) -> None:
    """Create or update the Temporal Schedule for a promoted table."""
    temporal = sync_connect()
    schedule = _build_schedule(promoted_table)
    schedule_id = promoted_table.schedule_id

    if create:
        create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=trigger_immediately)
        return

    try:
        update_schedule(temporal, id=schedule_id, schedule=schedule)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=trigger_immediately)
        else:
            raise


async def a_sync_promote_table_schedule(
    promoted_table: ManagedWarehousePromotedTable,
    *,
    create: bool = False,
    trigger_immediately: bool = False,
) -> None:
    temporal = await async_connect()
    schedule = _build_schedule(promoted_table)
    schedule_id = promoted_table.schedule_id

    if create:
        await a_create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=trigger_immediately)
        return

    try:
        await a_update_schedule(temporal, id=schedule_id, schedule=schedule)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            await a_create_schedule(
                temporal, id=schedule_id, schedule=schedule, trigger_immediately=trigger_immediately
            )
        else:
            raise


def delete_promote_table_schedule(schedule_id: str) -> None:
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


async def a_delete_promote_table_schedule(schedule_id: str) -> None:
    temporal = await async_connect()
    try:
        await a_delete_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def trigger_promote_table_schedule(schedule_id: str) -> None:
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=schedule_id)


async def a_trigger_promote_table_schedule(schedule_id: str) -> None:
    temporal = await async_connect()
    await a_trigger_schedule(temporal, schedule_id=schedule_id)


def promote_table_schedule_exists(schedule_id: str) -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=schedule_id)
