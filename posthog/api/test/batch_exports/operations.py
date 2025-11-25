import time
import asyncio
import datetime as dt
import threading
from contextlib import contextmanager

from django.conf import settings
from django.test.client import Client as TestClient

import temporalio.client
import temporalio.worker
from asgiref.sync import async_to_sync
from rest_framework import status
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker

from posthog.models.utils import UUIDT

from products.batch_exports.backend.temporal import ACTIVITIES, WORKFLOWS


class ThreadedWorker(Worker):
    """A Temporal Worker that can run in a separate thread.

    Inteded to be used in sync tests that require a Temporal Worker.
    """

    @contextmanager
    def run_in_thread(self):
        """Run a Temporal Worker in a thread.

        Don't use this outside of tests. Once PostHog is fully async we can get rid of this.
        """
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=self.run_using_loop, daemon=True, args=(loop,))
        t.start()

        try:
            while not self.is_running:
                time.sleep(0.1)
            yield
        finally:
            self._shutdown_event.set()
            # Give the worker a chance to shut down before exiting
            max_wait = 10.0
            while t.is_alive() and max_wait > 0:
                time.sleep(0.1)
                max_wait -= 0.1

    def run_using_loop(self, loop):
        """Setup an event loop to run the Worker.

        Using async_to_sync(Worker.run) causes a deadlock.
        """
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(super().run())
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()


@contextmanager
def start_test_worker(temporal: TemporalClient):
    with ThreadedWorker(
        client=temporal,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=dt.timedelta(seconds=5),
    ).run_in_thread():
        yield


def create_batch_export(client: TestClient, team_id: int, batch_export_data: dict | str):
    return client.post(
        f"/api/projects/{team_id}/batch_exports",
        batch_export_data,
        content_type="application/json",
    )


def create_batch_export_ok(client: TestClient, team_id: int, batch_export_data: dict | str):
    response = create_batch_export(client, team_id, batch_export_data)
    assert response.status_code == status.HTTP_201_CREATED, response.json()
    return response.json()


def pause_batch_export(client: TestClient, team_id: int, batch_export_id: UUIDT):
    return client.post(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/pause")


def pause_batch_export_ok(client: TestClient, team_id: int, batch_export_id: UUIDT):
    response = pause_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def unpause_batch_export(client: TestClient, team_id: int, batch_export_id: UUIDT, backfill: bool = False):
    return client.post(
        f"/api/projects/{team_id}/batch_exports/{batch_export_id}/unpause",
        {"backfill": backfill},
        content_type="application/json",
    )


def unpause_batch_export_ok(client: TestClient, team_id: int, batch_export_id: UUIDT, backfill: bool = False):
    response = unpause_batch_export(client, team_id, batch_export_id, backfill)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def get_batch_export(client: TestClient, team_id: int, batch_export_id: UUIDT):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}")


def get_batch_export_ok(client: TestClient, team_id: int, batch_export_id: UUIDT):
    response = get_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def get_batch_export_runs(client: TestClient, team_id: int, batch_export_id: str):
    return client.get(
        f"/api/projects/{team_id}/batch_exports/{batch_export_id}/runs",
        content_type="application/json",
    )


def get_batch_export_runs_ok(client: TestClient, team_id: int, batch_export_id: str):
    response = get_batch_export_runs(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def delete_batch_export(client: TestClient, team_id: int, batch_export_id: UUIDT):
    return client.delete(f"/api/projects/{team_id}/batch_exports/{batch_export_id}")


def delete_batch_export_ok(client: TestClient, team_id: int, batch_export_id: UUIDT):
    response = delete_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response
    return response


def list_batch_exports(client: TestClient, team_id: int):
    return client.get(f"/api/projects/{team_id}/batch_exports")


def list_batch_exports_ok(client: TestClient, team_id: int):
    response = list_batch_exports(client, team_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def backfill_batch_export(
    client: TestClient, team_id: int, batch_export_id: str, start_at: str, end_at: str, legacy_endpoint: bool = False
):
    """Create a backfill for a BatchExport.

    If legacy_endpoint is True, use the old endpoint (since adding the backfills API, we've deprecated the old one).
    """
    if legacy_endpoint:
        url = f"/api/projects/{team_id}/batch_exports/{batch_export_id}/backfill"
    else:
        url = f"/api/projects/{team_id}/batch_exports/{batch_export_id}/backfills"

    return client.post(
        url,
        {"start_at": start_at, "end_at": end_at},
        content_type="application/json",
    )


def backfill_batch_export_ok(client: TestClient, team_id: int, batch_export_id: str, start_at: str, end_at: str):
    response = backfill_batch_export(client, team_id, batch_export_id, start_at, end_at)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def put_batch_export(client, team_id, batch_export_id, new_batch_export_data):
    return client.put(
        f"/api/projects/{team_id}/batch_exports/{batch_export_id}/",
        new_batch_export_data,
        content_type="application/json",
    )


def patch_batch_export(client, team_id, batch_export_id, new_batch_export_data):
    return client.patch(
        f"/api/projects/{team_id}/batch_exports/{batch_export_id}/",
        new_batch_export_data,
        content_type="application/json",
    )


def get_batch_export_log_entries(client: TestClient, team_id: int, batch_export_id: str, **extra):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/logs", extra)


def get_batch_export_run_log_entries(client: TestClient, team_id: int, batch_export_id: str, run_id, **extra):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/runs/{run_id}/logs", extra)


def cancel_batch_export_run(client: TestClient, team_id: int, batch_export_id: str, run_id):
    return client.post(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/runs/{run_id}/cancel")


def cancel_batch_export_run_ok(client: TestClient, team_id: int, batch_export_id: str, run_id):
    response = client.post(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/runs/{run_id}/cancel")
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def list_batch_export_backfills(client: TestClient, team_id: int, batch_export_id: str):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/backfills")


def list_batch_export_backfills_ok(client: TestClient, team_id: int, batch_export_id: str):
    response = list_batch_export_backfills(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def get_batch_export_backfill(client: TestClient, team_id: int, batch_export_id: str, backfill_id: str):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/backfills/{backfill_id}")


def get_batch_export_backfill_ok(client: TestClient, team_id: int, batch_export_id: str, backfill_id: str):
    response = get_batch_export_backfill(client, team_id, batch_export_id, backfill_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def cancel_batch_export_backfill(client: TestClient, team_id: int, batch_export_id: str, backfill_id: str):
    return client.post(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/backfills/{backfill_id}/cancel")


def cancel_batch_export_backfill_ok(client: TestClient, team_id: int, batch_export_id: str, backfill_id: str):
    response = cancel_batch_export_backfill(client, team_id, batch_export_id, backfill_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


@async_to_sync
async def wait_for_workflow_executions(
    temporal: temporalio.client.Client, query: str, timeout: int = 30, sleep: int = 1
):
    """Wait for Workflow Executions matching query."""
    workflows = [workflow async for workflow in temporal.list_workflows(query=query)]

    total = 0
    while not workflows:
        if total > timeout:
            raise TimeoutError(f"No backfill Workflow Executions after {timeout} seconds")

        total += sleep
        await asyncio.sleep(sleep)
        workflows = [workflow async for workflow in temporal.list_workflows(query=query)]

    return workflows
