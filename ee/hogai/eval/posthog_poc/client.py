from __future__ import annotations

import os
import json
from pathlib import Path

from posthoganalytics import Posthog

from .utils import MAX_ERROR_LENGTH, truncate_text, without_none


class PostHogEvalClient:
    def __init__(
        self,
        analytics_client: Posthog,
        *,
        event_name: str = "$ai_evaluation",
        export_path: str | Path | None = None,
    ):
        self.analytics_client = analytics_client
        self.event_name = event_name
        self.export_path = Path(export_path) if export_path else None

    @classmethod
    def from_env(cls) -> PostHogEvalClient:
        host = os.getenv("POSTHOG_EVALS_HOST")
        api_key = os.getenv("POSTHOG_EVALS_PROJECT_API_KEY")
        if not host or not api_key:
            raise RuntimeError("POSTHOG_EVALS_HOST and POSTHOG_EVALS_PROJECT_API_KEY are required")

        export_path = os.getenv("POSTHOG_EVALS_EXPORT_PATH")
        if not export_path and os.getenv("EXPORT_EVAL_RESULTS"):
            export_path = "posthog_eval_results.jsonl"

        analytics_client = Posthog(api_key, host=host)
        return cls(analytics_client, export_path=export_path)

    def capture_evaluation(
        self,
        *,
        distinct_id: str,
        evaluation_type: str,
        experiment_id: str,
        experiment_name: str,
        experiment_item_id: str,
        experiment_item_name: str,
        metric_name: str,
        metric_version: str,
        result_type: str,
        status: str,
        score: float | None,
        score_min: float | None,
        score_max: float | None,
        trace_id: str | None,
        input_text: str | None,
        output_text: str | None,
        expected_text: str | None,
        reasoning: str | None,
        dataset_id: str | None = None,
        dataset_item_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        properties = without_none(
            {
                "$ai_evaluation_type": evaluation_type,
                "$ai_experiment_id": experiment_id,
                "$ai_experiment_name": experiment_name,
                "$ai_experiment_item_id": experiment_item_id,
                "$ai_experiment_item_name": experiment_item_name,
                "$ai_metric_name": metric_name,
                "$ai_metric_version": metric_version,
                "$ai_result_type": result_type,
                "$ai_status": status,
                "$ai_score": score if status == "ok" else None,
                "$ai_score_min": score_min if status == "ok" else None,
                "$ai_score_max": score_max if status == "ok" else None,
                "$ai_dataset_id": dataset_id,
                "$ai_dataset_item_id": dataset_item_id,
                "$ai_trace_id": trace_id,
                "$ai_input": input_text,
                "$ai_output": output_text,
                "$ai_expected": expected_text,
                "$ai_reasoning": reasoning,
                "$ai_error_code": error_code,
                "$ai_error_message": truncate_text(error_message, max_length=MAX_ERROR_LENGTH),
            }
        )

        self.analytics_client.capture(
            distinct_id=distinct_id,
            event=self.event_name,
            properties=properties,
        )

        if self.export_path:
            self.export_path.parent.mkdir(parents=True, exist_ok=True)
            with self.export_path.open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "event": self.event_name,
                            "distinct_id": distinct_id,
                            "properties": properties,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                    + "\n"
                )

    def flush(self) -> None:
        self.analytics_client.flush()

    def shutdown(self) -> None:
        self.analytics_client.shutdown()
