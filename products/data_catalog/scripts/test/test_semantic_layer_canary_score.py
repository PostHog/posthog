import re
import json
from datetime import UTC, datetime

import pytest

import httpx

from products.data_catalog.scripts.semantic_layer_canary_score import (
    BatchWindow,
    CanaryApiClient,
    UnknownRouting,
    evaluation_event,
    expectations_for,
    reconstruct_batch,
    score_case,
    score_results,
)

METRIC = "web_sessions_daily"
QUESTION = "How many sessions did the site get each day?"
DATASET_ID = "dataset-1"
REVISION = 42
WINDOW = BatchWindow(
    start=datetime(2026, 9, 10, 16, 54, 23, tzinfo=UTC),
    end=datetime(2026, 9, 10, 17, 17, 23, tzinfo=UTC),
)
INSIDE_WINDOW = "2026-09-10T17:00:00Z"
BEFORE_WINDOW = "2026-09-10T10:00:00Z"


def _entry(update: dict) -> dict:
    return {
        "timestamp": "2026-09-09T18:52:26.000Z",
        "notification": {"method": "session/update", "params": {"update": update}},
    }


def _tool_call(call_id: str, tool_name: str, raw_input: dict) -> list[dict]:
    return [
        _entry(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "_meta": {"claudeCode": {"toolName": tool_name}},
                "rawInput": raw_input,
            }
        ),
        _entry(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": "completed",
                "rawOutput": "{}",
            }
        ),
    ]


def _log(*entry_groups: list[dict]) -> str:
    return "\n".join(json.dumps(entry) for group in entry_groups for entry in group)


def _case(**overrides: object) -> dict:
    return {
        "case_id": "web-sessions-daily",
        "category": "direct_match",
        "expected_metric": METRIC,
        "expected_routing": "canonical_metric",
        "status": "completed",
        "task_id": "task-1",
        "task_run_id": "run-1",
        "task_url": "https://us.posthog.test/project/2/tasks/task-1?runId=run-1",
        "question": QUESTION,
    } | overrides


def _question_permission_request(question: str) -> list[dict]:
    return [
        {
            "timestamp": "2026-09-10T17:01:00.000Z",
            "notification": {
                "method": "session/request_permission",
                "params": {
                    "toolCall": {
                        "toolCallId": "call-q",
                        "_meta": {"codeToolKind": "question", "questions": [{"question": question}]},
                    }
                },
            },
        }
    ]


def _dataset_item(expected_routing: str = "canonical_metric") -> dict:
    return {
        "id": "item-1",
        "input": {"question": QUESTION},
        "expected_output": {
            "expected_metric": METRIC,
            "expected_routing": expected_routing,
            "expected_behavior": "Run the approved metric and summarize its output.",
        },
        "metadata": {"case_id": "web-sessions-daily", "category": "direct_match", "enabled": True},
    }


def _task(task_id: str, *, description: str = QUESTION, created_at: str = INSIDE_WINDOW) -> dict:
    return {"id": task_id, "description": description, "created_at": created_at, "title": description}


def _run(run_id: str, status: str, *, created_at: str = INSIDE_WINDOW) -> dict:
    return {"id": run_id, "status": status, "created_at": created_at}


def _batch_client(
    *,
    tasks: list[dict],
    runs_by_task: dict[str, list[dict]],
    logs_by_run: dict[str, list[dict]],
    expected_routing: str = "canonical_metric",
) -> CanaryApiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/datasets/"):
            return httpx.Response(
                200,
                json={"results": [{"id": DATASET_ID, "name": "semantic-layer-canaries-v1", "current_revision": 7}]},
            )
        if path.endswith("/dataset_items/"):
            assert request.url.params["revision"] == str(REVISION)
            return httpx.Response(200, json={"next": None, "results": [_dataset_item(expected_routing)]})
        if path.endswith("/tasks/"):
            assert request.url.params["origin_product"] == "posthog_ai"
            return httpx.Response(200, json={"next": None, "results": tasks})
        runs_match = re.fullmatch(r".*/tasks/([^/]+)/runs/", path)
        if runs_match:
            return httpx.Response(200, json={"results": runs_by_task[runs_match.group(1)]})
        log_match = re.fullmatch(r".*/tasks/[^/]+/runs/([^/]+)/session_logs/", path)
        assert log_match, path
        return httpx.Response(200, json=logs_by_run[log_match.group(1)], headers={"X-Has-More": "false"})

    return CanaryApiClient(
        host="https://us.posthog.test", project_id=2, api_key="key", transport=httpx.MockTransport(handler)
    )


def _score_batch(client: CanaryApiClient) -> tuple[dict, dict]:
    results = reconstruct_batch(client, dataset_name="semantic-layer-canaries-v1", revision=REVISION, window=WINDOW)
    rows = score_results(client, results)
    assert len(rows) == 1
    return results, rows[0]


class TestExpectationsForRouting:
    @pytest.mark.parametrize(
        "routing,expected_keys",
        [
            ("clarify", {"clarification_asked", "canonical_metric_run"}),
            ("no_match", {"metrics_catalog_before_data_discovery", "canonical_metric_run"}),
            (
                "canonical_metric",
                {
                    "metrics_catalog_before_data_discovery",
                    "canonical_metric_run",
                    "metric_describe_before_adapted_sql",
                },
            ),
            (
                "derive_from_approved",
                {
                    "metrics_catalog_before_data_discovery",
                    "canonical_metric_run",
                    "metric_describe_before_adapted_sql",
                    "proposed_metric_not_run",
                },
            ),
        ],
    )
    def test_known_routings_map_to_their_checks(self, routing: str, expected_keys: set[str]) -> None:
        assert set(expectations_for(routing, METRIC)) == expected_keys

    def test_an_unknown_routing_is_rejected_rather_than_guessed(self) -> None:
        with pytest.raises(UnknownRouting):
            expectations_for("vibes", METRIC)


class TestScoreCase:
    def test_catalog_then_canonical_run_passes(self) -> None:
        raw_log = _log(
            _tool_call("call-1", "metric-list", {}),
            _tool_call("call-2", "data-catalog-metric-run", {"name": METRIC}),
        )

        row = score_case(_case(), raw_log)

        assert row["verdict"] == "pass"
        assert row["failed_checks"] == []

    def test_schema_discovery_before_the_catalog_fails(self) -> None:
        raw_log = _log(
            _tool_call("call-1", "read-data-schema", {"query": {"kind": "events"}}),
            _tool_call("call-2", "execute-sql", {"query": "select count() from events"}),
        )

        row = score_case(_case(), raw_log)

        assert row["verdict"] == "fail"
        assert "metrics_catalog_before_data_discovery" in row["failed_checks"]
        assert "canonical_metric_run" in row["failed_checks"]

    def test_a_clarifying_question_before_any_data_call_passes(self) -> None:
        raw_log = _log(
            _tool_call("call-1", "metric-list", {}),
            _tool_call("call-2", "AskUserQuestion", {"questions": [{"question": "Which customers?"}]}),
        )

        row = score_case(_case(expected_routing="clarify", expected_metric=None), raw_log)

        assert row["verdict"] == "pass"

    def test_answering_from_data_instead_of_asking_fails(self) -> None:
        raw_log = _log(
            _tool_call("call-1", "metric-list", {}),
            _tool_call("call-2", "data-catalog-metric-run", {"name": METRIC}),
            _tool_call("call-3", "AskUserQuestion", {"questions": [{"question": "Which customers?"}]}),
        )

        row = score_case(_case(expected_routing="clarify", expected_metric=None), raw_log)

        assert row["verdict"] == "fail"
        assert "clarification_asked" in row["failed_checks"]

    def test_running_the_proposed_metric_fails_a_derive_case(self) -> None:
        raw_log = _log(
            _tool_call("call-1", "metric-list", {}),
            _tool_call("call-2", "metric-describe", {"name": METRIC}),
            _tool_call("call-3", "data-catalog-metric-run", {"name": METRIC}),
        )

        row = score_case(_case(expected_routing="derive_from_approved"), raw_log)

        assert row["verdict"] == "fail"
        assert row["failed_checks"] == ["proposed_metric_not_run"]

    def test_adapted_sql_without_describe_is_advisory_only(self) -> None:
        raw_log = _log(
            _tool_call("call-1", "metric-list", {}),
            _tool_call("call-2", "data-catalog-metric-run", {"name": METRIC}),
            _tool_call("call-3", "execute-sql", {"query": "select count() from events"}),
        )

        row = score_case(_case(), raw_log)

        assert row["verdict"] == "pass"
        assert row["advisory_checks"] == ["metric_describe_before_adapted_sql"]

    def test_a_run_without_a_confirmed_terminal_status_is_not_scored(self) -> None:
        row = score_case(_case(status="failed"), "")

        assert row["verdict"] == "unscored"
        assert "failed_checks" not in row


class TestBatchReconstruction:
    def test_scores_the_single_completed_run_from_its_full_log(self) -> None:
        client = _batch_client(
            tasks=[_task("task-1")],
            runs_by_task={"task-1": [_run("run-1", "completed")]},
            logs_by_run={
                "run-1": _tool_call("call-1", "metric-list", {})
                + _tool_call("call-2", "data-catalog-metric-run", {"name": METRIC})
            },
        )

        results, row = _score_batch(client)

        assert results["run_id"] == "tasks:2026-09-10T16:54:23Z:2026-09-10T17:17:23Z"
        assert results["dataset_revision"] == REVISION
        assert row["verdict"] == "pass"
        assert row["task_url"] == "https://us.posthog.test/project/2/tasks/task-1?runId=run-1"

    @pytest.mark.parametrize(
        "task",
        [
            _task("task-1", description=f"{QUESTION} Please."),
            _task("task-1", created_at=BEFORE_WINDOW),
        ],
        ids=["inexact_description", "outside_window"],
    )
    def test_ignores_tasks_that_are_not_an_exact_match_inside_the_window(self, task: dict) -> None:
        client = _batch_client(tasks=[task], runs_by_task={"task-1": [_run("run-1", "completed")]}, logs_by_run={})

        _results, row = _score_batch(client)

        assert row["status"] == "missing"
        assert row["verdict"] == "unscored"
        assert row["task_id"] is None

    @pytest.mark.parametrize(
        "runs,expected_status,expected_run_id",
        [
            (
                [
                    _run("run-1", "failed", created_at="2026-09-10T17:00:00Z"),
                    _run("run-2", "completed", created_at="2026-09-10T17:05:00Z"),
                ],
                "completed",
                "run-2",
            ),
            ([_run("run-1", "completed"), _run("run-2", "completed")], "duplicate", "run-2"),
            ([_run("run-1", "in_progress")], "incomplete", "run-1"),
            ([_run("run-1", "failed")], "failed", "run-1"),
        ],
        ids=["retry_then_completed", "two_completed", "still_running", "all_failed"],
    )
    def test_classifies_attempts_by_terminal_status(
        self, runs: list[dict], expected_status: str, expected_run_id: str
    ) -> None:
        client = _batch_client(
            tasks=[_task("task-1")],
            runs_by_task={"task-1": runs},
            logs_by_run={expected_run_id: _tool_call("call-1", "metric-list", {})},
        )

        _results, row = _score_batch(client)

        assert row["status"] == expected_status
        assert row["task_run_id"] == expected_run_id
        assert (row["verdict"] == "unscored") == (expected_status != "completed")

    def test_a_run_cancelled_behind_a_clarifying_question_is_scored_as_a_clarification(self) -> None:
        client = _batch_client(
            tasks=[_task("task-1")],
            runs_by_task={"task-1": [_run("run-1", "cancelled")]},
            logs_by_run={
                "run-1": _tool_call("call-1", "metric-list", {})
                + _tool_call("call-2", "AskUserQuestion", {"questions": [{"question": "Which customers?"}]})
                + _question_permission_request("Which customers?")
            },
            expected_routing="clarify",
        )

        _results, row = _score_batch(client)

        assert row["status"] == "completed"
        assert row["verdict"] == "pass"
        assert row["clarification_questions"] == ["Which customers?"]


class TestEvaluationEvent:
    @pytest.mark.parametrize(
        "row,applicable,score,reasoning",
        [
            (
                {"verdict": "pass", "failed_checks": [], "advisory_checks": []},
                True,
                1,
                '{"failed": [], "advisory": []}',
            ),
            (
                {"verdict": "unscored", "reason": "case status is missing, not completed"},
                False,
                None,
                "case status is missing, not completed",
            ),
        ],
        ids=["scored", "unscored"],
    )
    def test_marks_applicability_and_carries_the_task_link(
        self, row: dict, applicable: bool, score: int | None, reasoning: str
    ) -> None:
        base = _case(status="missing" if row["verdict"] == "unscored" else "completed")

        event = evaluation_event(run_id="tasks:a:b", dataset_revision=REVISION, row=base | row)

        properties = event["properties"]
        assert properties["$ai_evaluation_applicable"] is applicable
        assert properties.get("$ai_score") == score
        assert properties["$ai_reasoning"] == reasoning
        assert properties["batch_id"] == "tasks:a:b"
        assert properties["task_url"] == base["task_url"]
        assert "api_key" not in event


class TestCanaryApiClient:
    def test_reads_every_page_before_scoring(self) -> None:
        pages = [[{"page": 0}, {"page": 1}], [{"page": 2}]]
        seen_offsets: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            offset = request.url.params.get("offset")
            seen_offsets.append(offset)
            index = int(offset or 0) // 2
            return httpx.Response(
                200,
                json=pages[index],
                headers={"X-Has-More": "true" if index + 1 < len(pages) else "false"},
            )

        with CanaryApiClient(
            host="https://us.posthog.test",
            project_id=2,
            api_key="key",
            transport=httpx.MockTransport(handler),
        ) as client:
            raw_log = client.read_full_log("task-1", "run-1")

        assert seen_offsets == ["0", "2"]
        assert raw_log.splitlines() == ['{"page": 0}', '{"page": 1}', '{"page": 2}']
