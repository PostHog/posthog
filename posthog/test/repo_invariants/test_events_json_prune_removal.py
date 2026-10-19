from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EVENTS_JSON_TARGETS = REPO_ROOT / ".github" / "new-events-schema-targets.txt"
PRUNE_MODULES = (
    "posthog/test/events_schema_prune.py",
    "posthog/test/events_schema_recorder.py",
    "posthog/test/test_events_schema_prune.py",
    "posthog/test/test_events_schema_recorder.py",
)
PRUNE_WIRING = (
    "conftest.py",
    ".github/workflows/ci-backend.yml",
    ".github/workflows/ci-backend-update-test-timing.yml",
    ".depot/workflows/ci-backend.yml",
)
PRUNE_MARKERS = ("events_schema_prune", "events_schema_recorder", "events-schema-prune", "events-schema-record")


def test_prune_machinery_leaves_with_the_events_json_leg() -> None:
    if EVENTS_JSON_TARGETS.exists():
        return
    leftovers = [path for path in PRUNE_MODULES if (REPO_ROOT / path).exists()]
    leftovers += [
        path
        for path in PRUNE_WIRING
        if (REPO_ROOT / path).exists() and any(marker in (REPO_ROOT / path).read_text() for marker in PRUNE_MARKERS)
    ]
    assert not leftovers, (
        f"{EVENTS_JSON_TARGETS.name} is gone, so the events_json leg no longer runs and nothing records or "
        f"prunes its tests. Delete the prune machinery with it, including this test: {leftovers}"
    )
