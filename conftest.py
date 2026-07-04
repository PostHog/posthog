import gc
import os
import warnings
from pathlib import Path

import pytest

# Test-session boot — plugin imports and importing every collected test module —
# allocates almost exclusively permanent objects, so automatic cyclic GC during that
# phase only adds pauses (seconds on a full-tree CI shard collection). Run the boot
# with GC off, then freeze the survivors into the permanent generation so the
# collector never rescans them during the test phase. Tests themselves run with GC
# enabled as usual. (django.setup() runs in pytest-django's load_initial_conftests,
# before conftest files load, so it stays outside the window.)
gc.disable()


def _end_gc_boot_window() -> None:
    if gc.isenabled():
        return
    # Deliberately no gc.collect() before the freeze: sweeping the boot garbage
    # (including items deselected by pytest-split sharding — measured at ~7k cyclic
    # objects for a 5-way shard of posthog/api/test) costs ~0.5s per invocation but
    # reclaims only ~1MB, so the garbage gets frozen along with the survivors.
    gc.freeze()
    gc.enable()
    # gc.get_referrers() cannot see referrers in the frozen permanent generation,
    # which turns hypothesis's register_random() liveness check into a false positive
    # for Randoms registered after the freeze (e.g. trio's module-level instance,
    # registered when hypothesis is first imported). Refcounts are unaffected, so the
    # ReferenceError path for real misuse still works; only the warning is spurious.
    warnings.filterwarnings("ignore", message=r"It looks like `register_random` was passed")


def pytest_collection_finish() -> None:
    _end_gc_boot_window()


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop() -> None:
    # Safety net for processes that never run a local collection (e.g. the
    # pytest-xdist controller): end the window before the test loop starts.
    _end_gc_boot_window()


def pytest_unconfigure() -> None:
    # Frozen objects skip the final cyclic collections of interpreter shutdown, so their
    # finalizers run in the late teardown phase where extension modules may already be
    # gone — observed as exit code 139 (SIGSEGV) on the Temporal CI shards. Restore the
    # default heap state so shutdown behaves exactly as without the boot window.
    gc.unfreeze()


if os.environ.get("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", "").lower() in ("1", "true", "t", "y", "yes", "on"):
    from syrupy.extensions.amber import AmberSnapshotExtension
    from syrupy.location import PyTestLocation

    class _NewEventsSchemaAmberExtension(AmberSnapshotExtension):
        @classmethod
        def dirname(cls, *, test_location: PyTestLocation) -> str:
            return str(Path(test_location.filepath).parent / "__snapshots__" / "new_events_schema")

    @pytest.fixture
    def snapshot(snapshot):
        # New-events-schema runs keep a second, fully separate set of .ambr files so the two CI
        # modes can never read or rewrite each other's snapshots (a shared file gets its
        # other-mode blocks deleted on --snapshot-update).
        return snapshot.use_extension(_NewEventsSchemaAmberExtension)


@pytest.fixture(autouse=True)
def _activate_personhog_fake(request):
    """Force all person/group reads through the personhog fake for every test.

    The fake is seeded explicitly by the test helpers in posthog.test.persons
    (create_person, create_group, etc.).  While the fake is active, ORM access to
    persons-DB models raises (PersonsDBORMBlockedError) so nothing can silently
    fall back to the persons DB.

    Tests that exercise the persons DB layer itself (sync, backfill, maintenance
    commands) opt out with ``@pytest.mark.persons_db_direct`` — either on the
    class/function or as a module-level ``pytestmark``.
    """
    if request.node.get_closest_marker("persons_db_direct"):
        yield
        return
    from posthog.personhog_client.fake_client import activate_personhog_fake  # noqa: PLC0415, I001 — lazy import avoids connecting signals before Django is ready

    with activate_personhog_fake():
        yield


@pytest.fixture(autouse=True)
def _clean_persons_db_for_direct_tests(request):
    """Truncate the persons DB before each persons_db_direct test.

    These tests seed the persons DB through off-Django psycopg (posthog.test.persons), which
    commits outside Django's per-test transaction and so is NOT rolled back at teardown. Because
    team ids reset every test (the main DB rolls back), leaked rows from a prior test would bleed
    into the next one's reused team id. Truncating before the test (when no Django persons
    transaction holds locks yet) clears that carryover without risking a TRUNCATE lock hang.
    """
    if not request.node.get_closest_marker("persons_db_direct"):
        yield
        return

    from posthog.persons_db import persons_db_connection  # noqa: PLC0415

    with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename NOT LIKE 'pg_%' AND tablename NOT LIKE '_sqlx_%' AND tablename != '_persons_migrations'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        if tables:
            cursor.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
    yield
