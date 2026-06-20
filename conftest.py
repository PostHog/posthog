import gc
import warnings

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


@pytest.fixture(autouse=True)
def _activate_personhog_fake(request: pytest.FixtureRequest):
    """Route person/group reads through the in-memory personhog fake for every test.

    Production removed the ORM fallback from person/group data access, so without an
    active personhog client those reads raise. We activate ``FakePersonHogClient`` and
    mirror ORM writes into it (see ``posthog/test/personhog_fake.py``).

    The personhog client's own unit tests manage the client/gate themselves and assert
    on real (un-faked) behavior, so they opt out.
    """
    if "personhog_client" in str(request.node.path):
        yield
        return

    # Imported lazily so the heavy posthog.models import stays off the conftest-load path.
    from posthog.test.personhog_fake import activate_personhog_fake  # noqa: PLC0415

    with activate_personhog_fake():
        yield
