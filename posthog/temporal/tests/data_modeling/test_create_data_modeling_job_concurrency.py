import time
import asyncio
import threading
from typing import Any

import pytest
import unittest.mock

from django.db import connection, transaction

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities.create_data_modeling_job import (
    CreateDataModelingJobInputs,
    _create_data_modeling_job,
)

from products.data_modeling.backend.facade.api import NodeMoveError, lock_dag, move_saved_query_to_dag
from products.data_modeling.backend.facade.models import DAG, DataModelingJob, DataModelingJobStatus, Node

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

BLOCKED_DEADLINE_SECONDS = 30


def wait_until_another_backend_waits_on_a_lock() -> bool:
    """Whether some other connection is parked on a lock this test database can grant.

    Polled rather than slept on, so the wait ends as soon as the other thread reaches its lock
    instead of after a guessed interval. `pg_locks` is read rather than `pg_stat_activity`
    because the caller polls from inside an open transaction, and Postgres caches the backend
    status snapshot `pg_stat_activity` reports for the length of one. A transaction the waiter
    is queued behind is recorded with no database of its own, so both rows count.
    """
    deadline = time.monotonic() + BLOCKED_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE NOT granted AND pid <> pg_backend_pid() "
                "AND (database IS NULL OR database = (SELECT oid FROM pg_database WHERE datname = current_database()))"
            )
            if cursor.fetchone()[0] > 0:
                return True
        time.sleep(0.05)
    return False


async def test_a_move_cannot_land_between_a_job_reading_a_placement_and_inserting_it(ateam, adag, anode, asaved_query):
    destination = await database_sync_to_async(DAG.objects.create)(team=ateam, name="destination")
    refusals: list[str] = []

    def move_on_another_connection() -> None:
        # A thread gets its own connection, so this move commits instead of joining the job's
        # transaction and rolling back with it.
        try:
            move_saved_query_to_dag(ateam.pk, asaved_query.id, destination.id)
        except NodeMoveError as e:
            refusals.append(e.reason)
        finally:
            connection.close()

    real_create = DataModelingJob.objects.create
    movers: list[threading.Thread] = []

    def create_after_a_move_tries_to_land(*args: Any, **kwargs: Any) -> Any:
        # Between the placement read and this insert is the window where a move whose Running
        # check ran before the job row existed could still commit, leaving the job pointing at a
        # DAG the node has left.
        mover = threading.Thread(target=move_on_another_connection)
        mover.start()
        movers.append(mover)
        assert wait_until_another_backend_waits_on_a_lock(), "the move was not held off by the job's DAG lock"
        return real_create(*args, **kwargs)

    inputs = CreateDataModelingJobInputs(team_id=ateam.pk, node_id=str(anode.id), dag_id=str(adag.id))
    with unittest.mock.patch.object(DataModelingJob.objects, "create", side_effect=create_after_a_move_tries_to_land):
        created = await _create_data_modeling_job(inputs, "test-workflow-id", "test-run-id")

    assert len(movers) == 1
    movers[0].join(timeout=BLOCKED_DEADLINE_SECONDS)
    assert not movers[0].is_alive()

    assert refusals == ["materializing"]
    node = await database_sync_to_async(Node.objects.get)(id=anode.id)
    assert node.dag_id == adag.id
    job = await database_sync_to_async(DataModelingJob.objects.get)(id=created.job_id)
    assert job.status == DataModelingJobStatus.RUNNING


async def test_a_job_start_does_not_wait_behind_a_dag_edge_writer(ateam, adag, anode):
    held = threading.Event()
    release = threading.Event()

    def hold_the_dag_edge_lock_on_another_connection() -> None:
        try:
            with transaction.atomic():
                lock_dag(ateam.pk, adag.id)
                held.set()
                release.wait(timeout=BLOCKED_DEADLINE_SECONDS)
        finally:
            connection.close()

    writer = threading.Thread(target=hold_the_dag_edge_lock_on_another_connection)
    writer.start()
    try:
        assert held.wait(timeout=BLOCKED_DEADLINE_SECONDS)
        inputs = CreateDataModelingJobInputs(team_id=ateam.pk, node_id=str(anode.id), dag_id=str(adag.id))
        created = await asyncio.wait_for(
            _create_data_modeling_job(inputs, "test-workflow-id", "test-run-id"), timeout=BLOCKED_DEADLINE_SECONDS / 3
        )
    finally:
        release.set()
        writer.join(timeout=BLOCKED_DEADLINE_SECONDS)

    job = await database_sync_to_async(DataModelingJob.objects.get)(id=created.job_id)
    assert job.status == DataModelingJobStatus.RUNNING
