from __future__ import annotations

import sys
import json
import subprocess
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).with_name("ci_infra_retry.py")
SPEC = importlib.util.spec_from_file_location("ci_infra_retry", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ci_infra_retry = importlib.util.module_from_spec(SPEC)
sys.modules["ci_infra_retry"] = ci_infra_retry
SPEC.loader.exec_module(ci_infra_retry)


def _job(
    *,
    conclusion: str | None = "failure",
    runner_name: str | None = "depot-zrrsk82t2h",
) -> ci_infra_retry.Job:  # type: ignore[name-defined]
    return ci_infra_retry.Job(
        id=123,
        name="Discover product tests",
        conclusion=conclusion,
        runner_name=runner_name,
        html_url="https://github.com/PostHog/posthog/actions/runs/1/job/123",
    )


DEPOT_CANCELED_LOG = "\n".join(
    [
        "Runner name: 'depot-zrrsk82t2h'",
        "##[error]Step canceled by GitHub (see: https://depot.dev/docs/github-actions/troubleshooting#error-step-canceled-by-github)",
    ]
)


def test_classifies_depot_step_canceled_as_rerun_when_enabled() -> None:
    decision = ci_infra_retry.classify_job(_job(), DEPOT_CANCELED_LOG, run_attempt=1, max_reruns=1, enabled=True)

    assert decision.action == ci_infra_retry.DecisionAction.RERUN


def test_classifies_depot_step_canceled_as_disabled_when_not_enabled() -> None:
    decision = ci_infra_retry.classify_job(_job(), DEPOT_CANCELED_LOG, run_attempt=1, max_reruns=1, enabled=False)

    assert decision.action == ci_infra_retry.DecisionAction.SKIP_DISABLED


def test_does_not_rerun_without_exact_infra_marker() -> None:
    decision = ci_infra_retry.classify_job(_job(), "FAILED test_real_regression.py::test_bug", 1, 1, True)

    assert decision.action == ci_infra_retry.DecisionAction.SKIP_NOT_INFRA


def test_does_not_rerun_non_depot_runner() -> None:
    decision = ci_infra_retry.classify_job(_job(runner_name="GitHub Actions 1"), DEPOT_CANCELED_LOG, 1, 1, True)

    assert decision.action == ci_infra_retry.DecisionAction.SKIP_NOT_INFRA


def test_respects_attempt_cap() -> None:
    decision = ci_infra_retry.classify_job(_job(), DEPOT_CANCELED_LOG, run_attempt=2, max_reruns=1, enabled=True)

    assert decision.action == ci_infra_retry.DecisionAction.SKIP_CAP_REACHED


def test_load_workflow_run(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "workflow_run": {
                    "id": 456,
                    "name": "Backend CI",
                    "conclusion": "failure",
                    "run_attempt": 1,
                    "html_url": "https://github.com/PostHog/posthog/actions/runs/456",
                }
            }
        )
    )

    workflow_run = ci_infra_retry.load_workflow_run(event_path)

    assert workflow_run.id == 456
    assert workflow_run.name == "Backend CI"


def test_load_workflow_run_requires_workflow_run_payload(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text("{}")

    with pytest.raises(ValueError, match="workflow_run"):
        ci_infra_retry.load_workflow_run(event_path)


def test_main_fails_open_on_github_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ci_infra_retry,
        "parse_args",
        lambda: SimpleNamespace(
            repo="PostHog/posthog",
            event_path="/tmp/event.json",
            enabled=True,
            dry_run=False,
            max_reruns=1,
        ),
    )
    monkeypatch.setattr(
        ci_infra_retry,
        "load_workflow_run",
        lambda _path: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["gh", "api"])),
    )

    assert ci_infra_retry.main() == 0
