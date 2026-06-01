import ast
from pathlib import Path

# Registry + guard for tests that need the *real* Temporal docker container.
#
# Backend tests reach Temporal one of two ways, and only one needs the container:
#
#   - In-process test server: temporalio.testing.WorkflowEnvironment.start_time_skipping()
#     / ActivityEnvironment. Spawns an ephemeral temporal-test-server in the test
#     process. Needs NO docker container. This is the preferred harness — see
#     posthog/temporal/README.md ("Testing patterns").
#   - Real docker container: sync_connect() / async_connect() / connect() from
#     posthog.temporal.common.client, or start_test_worker() (boots a real Worker
#     bound to a real client). These only pass when the docker `temporal` profile
#     is running.
#
# In the Core CI segment (`pytest posthog ee/`, see .github/workflows/ci-backend.yml)
# the docker container is booted for every shard, so a real-container dependency
# added to a Core test "just works" locally and in CI — silently coupling the Core
# segment to a service most of its tests don't need. This guard makes that coupling
# explicit: any unregistered real-container dependency fails here with instructions.
#
# If this test fails for a file you added/changed, pick one:
#   1. (preferred) Switch to WorkflowEnvironment.start_time_skipping() / ActivityEnvironment
#      so the test needs no docker container at all.
#   2. Keep the real-container dependency, register the file below with a one-line reason,
#      AND make sure it runs under a CI segment that boots Temporal. For tests in the Core
#      tree (posthog/ + ee/) that means marking them @pytest.mark.temporal_container — the
#      Core segment deselects that marker and the TemporalCore segment runs it. (The eval
#      harness is the exception: it runs in ci-ai, not the Core Django job.)

REPO_ROOT = Path(__file__).resolve().parents[2]

_CLIENT_MODULE = "posthog.temporal.common.client"
_CLIENT_CONNECT_NAMES = {"connect", "sync_connect", "async_connect"}
_REAL_WORKER_NAMES = {"start_test_worker"}

# The Core + Temporal Django CI job collects posthog/ and ee/. posthog/temporal/ is
# the Temporal segment's own tree (container always available there), so it is out of
# scope for registration.
_SCAN_DIRS = ("posthog", "ee")
_EXCLUDE_PREFIXES = ("posthog/temporal/",)

# Known tests that require the real Temporal docker container. Keep this list small —
# every entry is a test that cannot run in a container-less segment.
REAL_CONTAINER_TESTS: dict[str, str] = {
    "posthog/api/test/batch_exports/conftest.py": "package-scoped temporal/temporal_worker fixtures connect + boot a real Worker",
    "posthog/api/test/test_team.py": "team-deletion tests boot a real Worker to assert batch-export schedule cleanup",
    "posthog/management/commands/test/test_update_batch_export_schedules.py": "connects to reconcile batch-export schedules",
    "posthog/management/commands/test/test_update_data_import_schedules.py": "connects to reconcile data-import schedules",
    "posthog/management/commands/test/test_backfill_batch_export_runs.py": "boots a real Worker to backfill batch-export runs",
    "ee/hogai/eval/sandboxed/conftest.py": "eval harness connects to terminate stale workflows (runs in ci-ai, not Core)",
}


def _is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "/test/" in f"/{rel}" or "/tests/" in f"/{rel}"


def _real_container_trigger_names(tree: ast.AST) -> set[str]:
    names = set(_REAL_WORKER_NAMES)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if node.module == _CLIENT_MODULE and alias.name in _CLIENT_CONNECT_NAMES:
                names.add(alias.asname or alias.name)
            elif alias.name in _REAL_WORKER_NAMES:
                names.add(alias.asname or alias.name)
    return names


def _calls_any(tree: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
        for node in ast.walk(tree)
    )


def _scan_real_container_tests() -> set[str]:
    found: set[str] = set()
    for scan_dir in _SCAN_DIRS:
        for path in (REPO_ROOT / scan_dir).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(_EXCLUDE_PREFIXES) or not _is_test_file(rel):
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            if _calls_any(tree, _real_container_trigger_names(tree)):
                found.add(rel)
    return found


def test_real_temporal_container_dependencies_are_registered():
    found = _scan_real_container_tests()
    registered = set(REAL_CONTAINER_TESTS)

    unregistered = sorted(found - registered)
    stale = sorted(registered - found)

    messages = []
    if unregistered:
        messages.append(
            "These test files call into the real Temporal docker container "
            "(sync_connect/async_connect/connect/start_test_worker) but are not registered:\n  "
            + "\n  ".join(unregistered)
            + "\n\nPrefer WorkflowEnvironment.start_time_skipping()/ActivityEnvironment (no container needed). "
            "If the real container is truly required, add the file to REAL_CONTAINER_TESTS in "
            f"{Path(__file__).relative_to(REPO_ROOT).as_posix()} with a reason, and ensure it runs under a "
            "CI segment that boots Temporal."
        )
    if stale:
        messages.append(
            "These files are registered as needing the real Temporal container but no longer call into it. "
            "Remove them from REAL_CONTAINER_TESTS:\n  " + "\n  ".join(stale)
        )

    assert not messages, "\n\n".join(messages)
