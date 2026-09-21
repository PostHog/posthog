import sys
import zipfile
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("collect_depot_backend_telemetry.py")
SPEC = importlib.util.spec_from_file_location("collect_depot_backend_telemetry", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules["collect_depot_backend_telemetry"] = collector
SPEC.loader.exec_module(collector)


def test_parse_artifacts_keeps_only_expected_inputs() -> None:
    payload = {
        "artifacts": [
            {
                "artifact_id": "a1",
                "run_id": "run1",
                "workflow_id": "wf1",
                "workflow_path": "ci-backend.yml",
                "name": "junit-results-backend-core-1",
                "size_bytes": 100,
                "attempt": 1,
                "created_at": "2026-09-21T16:20:54Z",
            },
            {
                "artifact_id": "a2",
                "run_id": "run1",
                "workflow_id": "wf1",
                "workflow_path": "ci-backend.yml",
                "name": "coverage-core-1",
                "size_bytes": 100,
                "attempt": 1,
                "created_at": "2026-09-21T16:20:54Z",
            },
        ]
    }

    assert [artifact.name for artifact in collector.parse_artifacts(payload, "run1", "wf1")] == [
        "junit-results-backend-core-1"
    ]


def test_select_attempt_uses_artifacts_created_during_the_github_rerun() -> None:
    artifacts = [
        collector.Artifact("a1", "junit-results-backend-core-1", 100, 1, datetime(2026, 9, 21, 16, tzinfo=UTC)),
        collector.Artifact("a2", "junit-results-backend-core-1", 100, 2, datetime(2026, 9, 21, 17, 5, tzinfo=UTC)),
        collector.Artifact("a3", "junit-results-backend-core-2", 100, 3, datetime(2026, 9, 21, 18, tzinfo=UTC)),
    ]

    attempt, selected = collector.select_attempt(
        artifacts,
        run_attempt=None,
        attempt_started_at="2026-09-21T17:00:00Z",
        attempt_finished_at="2026-09-21T17:10:00Z",
    )

    assert attempt == 2
    assert [artifact.artifact_id for artifact in selected] == ["a2"]


def test_select_attempt_does_not_reemit_initial_artifacts_during_a_rerun() -> None:
    artifacts = [
        collector.Artifact("a1", "junit-results-backend-core-1", 100, 1, datetime(2026, 9, 21, 17, 5, tzinfo=UTC))
    ]

    attempt, selected = collector.select_attempt(
        artifacts,
        run_attempt=None,
        attempt_started_at="2026-09-21T17:00:00Z",
        attempt_finished_at="2026-09-21T17:10:00Z",
    )

    assert attempt is None
    assert selected == []


def test_safe_extract_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../secret", "bad")

    with pytest.raises(ValueError, match="unsafe artifact member"):
        collector.safe_extract(archive, tmp_path / "output")


def test_validated_selection_uses_trusted_run_identity() -> None:
    properties = collector.validated_selection(
        {
            "suite": "backend",
            "mode": "selected",
            "selected_test_count": 4,
            "sha": "attacker",
            "run_id": "attacker",
        },
        pr_number=42,
        head_sha="abc123",
        head_ref="feature",
        run_id="run1",
    )

    assert properties["sha"] == "abc123"
    assert properties["run_id"] == "run1"
    assert properties["pr_number"] == 42
    assert properties["ci_engine"] == "depot"
