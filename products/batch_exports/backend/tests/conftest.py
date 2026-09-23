import gc
import sys
import random
import inspect
import threading
import urllib.parse
import urllib.request

import pytest

from django.conf import settings

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team


# TEMPORARY: find the test that hangs on the native-JSON events table in CI. Remove before merge.
def _write_pending_coroutines() -> None:
    for obj in gc.get_objects():
        frame = getattr(obj, "cr_frame", None) if inspect.iscoroutine(obj) else None
        if frame is None and inspect.isasyncgen(obj):
            frame = obj.ag_frame
        if frame is None or "posthog" not in frame.f_code.co_filename:
            continue
        sys.stderr.write(f"  pending {frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}\n")


def _write_clickhouse_processes() -> None:
    query = "SELECT query_id, round(elapsed), substring(replaceAll(query, '\\n', ' '), 1, 400) FROM system.processes FORMAT TSV"
    url = f"http://{settings.CLICKHOUSE_HOST}:8123/?" + urllib.parse.urlencode({"query": query})
    request = urllib.request.Request(
        url, headers={"X-ClickHouse-User": settings.CLICKHOUSE_USER, "X-ClickHouse-Key": settings.CLICKHOUSE_PASSWORD}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            sys.stderr.write("  clickhouse processes:\n" + response.read().decode() + "\n")
    except Exception as error:
        sys.stderr.write(f"  clickhouse processes unavailable: {error!r}\n")


@pytest.fixture(autouse=True)
def _dump_asyncio_tasks_on_hang(request):
    capture_manager = request.config.pluginmanager.getplugin("capturemanager")

    def dump() -> None:
        capture_manager.suspend_global_capture(in_=False)
        try:
            sys.stderr.write(f"\n=== HANG DUMP {request.node.nodeid} ===\n")
            _write_pending_coroutines()
            _write_clickhouse_processes()
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
