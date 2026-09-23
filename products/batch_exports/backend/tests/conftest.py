import gc
import sys
import random
import asyncio
import threading

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team


# TEMPORARY: find the test that hangs on the native-JSON events table in CI. Remove before merge.
@pytest.fixture(autouse=True)
def _dump_asyncio_tasks_on_hang(request):
    capture_manager = request.config.pluginmanager.getplugin("capturemanager")

    def dump() -> None:
        loops = [obj for obj in gc.get_objects() if isinstance(obj, asyncio.AbstractEventLoop) and obj.is_running()]
        capture_manager.suspend_global_capture(in_=False)
        try:
            sys.stderr.write(f"\n=== HANG DUMP {request.node.nodeid}: {len(loops)} running loop(s) ===\n")
            for loop in loops:
                for task in asyncio.all_tasks(loop):
                    sys.stderr.write(f"--- {task!r}\n")
                    task.print_stack(file=sys.stderr)
            sys.stderr.flush()
        finally:
            capture_manager.resume_global_capture()

    timer = threading.Timer(240, dump)
    timer.daemon = True
    timer.start()
    yield
    timer.cancel()


@pytest_asyncio.fixture
async def aorganization(db):
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

    yield org

    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    # need to use create here rather than acreate because TeamManager.create() has some custom logic
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team
    # Skip Temporal schedule cleanup — team.delete() CASCADE-deletes BatchExport
    # rows from the DB, and Temporal schedules in CI don't need explicit removal.
    # Calling delete_batch_exports() here can hang indefinitely because
    # sync_to_async threads blocked on gRPC cannot be cancelled by asyncio.
    await sync_to_async(team.delete)()
