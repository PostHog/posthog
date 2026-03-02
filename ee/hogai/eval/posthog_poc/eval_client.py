from __future__ import annotations

import json
from pathlib import Path

from .client import PostHogEvalClient


class FakeAnalyticsClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.flushed = False
        self.shut_down = False

    def capture(self, *, distinct_id: str, event: str, properties: dict) -> None:
        self.calls.append(
            {
                "distinct_id": distinct_id,
                "event": event,
                "properties": properties,
            }
        )

    def flush(self) -> None:
        self.flushed = True

    def shutdown(self) -> None:
        self.shut_down = True


def eval_capture_evaluation_matches_schema(tmp_path: Path) -> None:
    analytics_client = FakeAnalyticsClient()
    export_path = tmp_path / "posthog_eval_results.jsonl"
    client = PostHogEvalClient(analytics_client, export_path=export_path)

    client.capture_evaluation(
        distinct_id="eval-run-1",
        evaluation_type="offline",
        experiment_id="experiment-1",
        experiment_name="ticket_summary",
        experiment_item_id="case-1",
        experiment_item_name="funnel with no data",
        metric_name="ticket_summary_quality",
        metric_version="1",
        result_type="numeric",
        status="ok",
        score=1.0,
        score_min=0,
        score_max=1,
        trace_id="judge-trace-1",
        input_text="input",
        output_text="output",
        expected_text="expected",
        reasoning="Looks correct",
        dataset_id="dataset-1",
        dataset_item_id="dataset-item-1",
    )

    assert len(analytics_client.calls) == 1
    call = analytics_client.calls[0]
    assert call["event"] == "$ai_evaluation"
    assert call["properties"]["$ai_evaluation_type"] == "offline"
    assert call["properties"]["$ai_metric_name"] == "ticket_summary_quality"
    assert call["properties"]["$ai_trace_id"] == "judge-trace-1"

    exported = json.loads(export_path.read_text().splitlines()[0])
    assert exported["properties"]["$ai_experiment_item_id"] == "case-1"
    assert exported["properties"]["$ai_score"] == 1.0
