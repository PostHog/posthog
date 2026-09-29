import threading
from typing import Any

import pytest
import unittest.mock

from django.db import connection

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities.create_data_modeling_job import (
    CreateDataModelingJobInputs,
    _create_data_modeling_job,
)

from products.data_modeling.backend.facade.api import NodeMoveError, move_saved_query_to_dag
from products.data_modeling.backend.facade.models import DAG, DataModelingJob, DataModelingJobStatus, Node

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

# Long enough that a move which is not blocked finishes inside it, short enough that the blocked
# case does not slow the suite down.
BLOCKED_MOVE_WINDOW_SECONDS = 2


async def test_a_move_cannot_land_between_a_job_reading_a_placement_and_inserting_it(ateam, adag, anode, asaved_query):
    """The move refuses while a job of this query is Running, so job creation has to hold the DAG
    lock across its placement read and its insert. Otherwise the move's check runs before the job
    row exists, the move commits, and the job is left pointing at a DAG the node has left -- which
    every later activity of that run, including the one that records failure, cannot find."""
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
        mover = threading.Thread(target=move_on_another_connection)
        mover.start()
        mover.join(timeout=BLOCKED_MOVE_WINDOW_SECONDS)
        movers.append(mover)
        assert mover.is_alive(), "the move was not held off by the job's DAG lock"
        return real_create(*args, **kwargs)

    inputs = CreateDataModelingJobInputs(team_id=ateam.pk, node_id=str(anode.id), dag_id=str(adag.id))
    with unittest.mock.patch.object(DataModelingJob.objects, "create", side_effect=create_after_a_move_tries_to_land):
        created = await _create_data_modeling_job(inputs, "test-workflow-id", "test-run-id")

    assert len(movers) == 1
    movers[0].join(timeout=30)
    assert not movers[0].is_alive()

    assert refusals == ["materializing"]
    node = await database_sync_to_async(Node.objects.get)(id=anode.id)
    assert node.dag_id == adag.id
    job = await database_sync_to_async(DataModelingJob.objects.get)(id=created.job_id)
    assert job.status == DataModelingJobStatus.RUNNING
