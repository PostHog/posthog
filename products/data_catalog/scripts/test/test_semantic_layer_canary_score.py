import json

import pytest

import httpx

from products.data_catalog.scripts.semantic_layer_canary_score import (
    SessionLogClient,
    UnknownRouting,
    expectations_for,
    score_case,
)

METRIC = "web_sessions_daily"


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
        "question": "How many sessions did the site get each day?",
    } | overrides


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


class TestSessionLogClient:
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

        with SessionLogClient(
            host="https://us.posthog.test",
            project_id=2,
            api_key="key",
            transport=httpx.MockTransport(handler),
        ) as client:
            raw_log = client.read_full_log("task-1", "run-1")

        assert seen_offsets == ["0", "2"]
        assert raw_log.splitlines() == ['{"page": 0}', '{"page": 1}', '{"page": 2}']
