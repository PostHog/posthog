import datetime as dt
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("capture_depot_running_time.py")
SPEC = importlib.util.spec_from_file_location("capture_depot_running_time", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)

ENV = {
    "GITHUB_REPOSITORY": "PostHog/posthog",
    "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
    "GITHUB_REF": "refs/pull/1/merge",
    "GITHUB_WORKFLOW": "Backend CI on Depot",
    "GITHUB_RUN_NUMBER": "",
    "GITHUB_RUN_ID": "42",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_ACTOR": "octocat",
    "GITHUB_EVENT_NAME": "pull_request",
}
SHOWN = {
    "workflow": {"started_at": "2026-01-01T00:00:00Z"},
    "jobs": [
        {
            "job_key": "ci-backend.yml:django_tests",
            "job_display_name": "Django Tests Pass on Depot",
            "status": "failed",
            "attempts": [{"attempt": 1, "started_at": "2026-01-01T00:20:00Z", "finished_at": "2026-01-01T00:20:05Z"}],
        },
        {
            "job_key": "ci-backend.yml:django:matrix-01",
            "job_display_name": "Django tests - Core (1/2)",
            "status": "finished",
            "attempts": [
                {"attempt": 1, "started_at": "2026-01-01T00:01:00Z", "finished_at": "2026-01-01T00:11:00Z"},
                {"attempt": 2, "started_at": "2026-01-01T00:12:00Z", "finished_at": "2026-01-01T00:19:30Z"},
            ],
        },
        {
            "job_key": "ci-backend.yml:validate-product-yamls",
            "job_display_name": "Validate product.yaml owners",
            "status": "skipped",
            "started_at": "",
            "finished_at": "2026-01-01T00:00:40Z",
            "attempts": [],
        },
        {"job_key": "ci-backend.yml:django:_dynamicMatrix", "status": "skipped", "finished_at": "2026-01-01T00:00:50Z"},
        {
            "job_key": "ci-backend.yml:calculate-running-time",
            "job_display_name": "Calculate running time",
            "status": "running",
            "attempts": [{"attempt": 1, "started_at": "2026-01-01T00:20:10Z", "finished_at": ""}],
        },
    ],
}


def test_build_events_matches_the_action_event_shape() -> None:
    now = dt.datetime(2026, 1, 1, 0, 21, 30, tzinfo=dt.UTC)

    events = capture.build_events(SHOWN, "https://depot.dev/orgs/org/workflows/wf", "django_tests", ENV, now)

    group = {"workflow_run": "PostHog/posthog/42"}
    assert events[0] == {
        "distinct_id": "posthog-github-action",
        "timestamp": now.isoformat(),
        "event": "posthog-ci-running-time",
        "properties": {
            "duration_seconds": 1290,
            "url": "https://depot.dev/orgs/org/workflows/wf",
            "attempt": 1,
            "started_at": "2026-01-01T00:00:00Z",
            "conclusion": "failure",
            "runner": "depot-ci",
            "sha": ENV["GITHUB_SHA"],
            "ref": "refs/pull/1/merge",
            "workflow": "Backend CI on Depot",
            "runNumber": None,
            "runId": 42,
            "repository": "posthog",
            "repositoryOwner": "PostHog",
            "actor": "octocat",
            "actor_type": "human",
            "eventName": "pull_request",
            "$groups": group,
        },
    }
    assert events[1]["event"] == "$groupidentify"
    assert events[1]["distinct_id"] == "$workflow_run_PostHog/posthog/42"
    assert events[1]["properties"]["$group_set"] == {"conclusion": "failure"}
    assert [
        (e["properties"]["name"], e["properties"]["duration_seconds"], e["properties"]["conclusion"])
        for e in events[2:]
    ] == [
        ("Django Tests Pass on Depot", 5, "failure"),
        ("Django tests - Core (1/2)", 450, "success"),
        ("Validate product.yaml owners", 0, "skipped"),
    ]
    assert all(e["event"] == "posthog-ci-running-time-job" and e["properties"]["$groups"] == group for e in events[2:])
