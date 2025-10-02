import json
import hashlib
import urllib.parse
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime
from tempfile import TemporaryFile
from typing import Any
from uuid import UUID

from django.conf import settings

import botocore
from dagster_aws.s3 import S3Resource
from fastavro import parse_schema, writer
from pydantic_avro import AvroBase
from tenacity import retry, stop_after_attempt, wait_exponential

EVALS_S3_PREFIX = "ai_evals"

# objectstorage has only the default bucket in debug.
if settings.DEBUG:
    EVALS_S3_BUCKET = settings.OBJECT_STORAGE_BUCKET
else:
    EVALS_S3_BUCKET = settings.DAGSTER_AI_EVALS_S3_BUCKET


def get_consistent_hash_suffix(file_name: str, date: datetime | None = None, code_version: str | None = None) -> str:
    """
    Generate a consistent hash suffix that updates twice per month based on the filename.

    The hash changes on the 1st and 15th of each month, ensuring links update
    twice monthly while remaining consistent within each period.

    Args:
        file_name: The base filename to hash
        date: Optional date for testing, defaults to current date
        code_version: Optional code version for hash consistency

    Returns:
        A short hash string (8 characters) that's consistent within each half-month period
    """
    if date is None:
        date = datetime.now()

    # Determine which half of the month we're in
    half_month_period = 1 if date.day < 15 else 2

    # Create a seed that changes twice per month
    period_seed = f"{date.year}-{date.month:02d}-{half_month_period}"

    # Combine the period seed with the filename for consistent hashing
    hash_input = f"{period_seed}:{file_name}"
    if code_version:
        hash_input += f":{code_version}"

    # Generate a short, URL-safe hash
    hash_obj = hashlib.sha256(hash_input.encode("utf-8"))
    return hash_obj.hexdigest()[:8]


def compose_postgres_dump_path(project_id: int, dir_name: str, code_version: str | None = None) -> str:
    """Compose S3 path for Postgres dumps with consistent hashing"""
    hash_suffix = get_consistent_hash_suffix(dir_name, code_version=code_version)
    return f"{EVALS_S3_PREFIX}/postgres_models/{project_id}/{dir_name}/{hash_suffix}.avro"


def compose_clickhouse_dump_path(project_id: int, dir_name: str, code_version: str | None = None) -> str:
    """Compose S3 path for ClickHouse dumps with consistent hashing"""
    hash_suffix = get_consistent_hash_suffix(dir_name, code_version=code_version)
    return f"{EVALS_S3_PREFIX}/clickhouse_queries/{project_id}/{dir_name}/{hash_suffix}.avro"


def check_dump_exists(s3: S3Resource, file_key: str) -> bool:
    """Check if a file exists in S3"""
    try:
        s3.get_client().head_object(Bucket=EVALS_S3_BUCKET, Key=file_key)
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


@contextmanager
def dump_model(*, s3: S3Resource, schema: type[AvroBase], file_key: str):
    with TemporaryFile() as f:
        parsed_schema = parse_schema(schema.avro_schema())

        def dump(models: Sequence[AvroBase]):
            writer(f, parsed_schema, (model.model_dump() for model in models))

        yield dump

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4))
        def upload():
            f.seek(0)
            s3.get_client().upload_fileobj(f, EVALS_S3_BUCKET, file_key)

        upload()


EvaluationResults = list[dict[Any, Any]]


class ResultsFormatter:
    """Formats evaluation results into Slack-compatible markdown blocks."""

    def __init__(self, dataset_id: UUID, dataset_name: str, experiment_id: str):
        self.dataset_id = dataset_id
        self.dataset_name = dataset_name
        self.experiment_id = experiment_id

    def format(
        self,
        results: EvaluationResults,
        prev_results: EvaluationResults | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Format evaluation results into Slack blocks and markdown."""
        experiment_summaries = []
        for result in results:
            experiment_summary = self._format_experiment_summary(result, prev_results)
            experiment_summaries.append(experiment_summary)

        total_experiments = len(results)
        total_metrics = sum(len(result.get("scores", {})) for result in results)

        body_parts = [
            f"🧠 **AI eval results** for dataset [{self.dataset_name}](https://us.posthog.com/llm-analytics/datasets/{self.dataset_id})",
            f"Evaluated **{total_experiments}** experiment{'' if total_experiments == 1 else 's'}, comprising **{total_metrics}** metric{'' if total_metrics == 1 else 's'}.",
            *experiment_summaries,
        ]
        formatted_markdown = "\n\n".join(body_parts)
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": formatted_markdown}}]
        return blocks, formatted_markdown

    def _format_experiment_summary(self, result: dict[str, Any], prev_results: EvaluationResults | None) -> str:
        """Format a single experiment's results into a summary string."""
        prev_result = self._find_previous_result(result, prev_results)
        scores_text = self._format_scores(result, prev_result)
        metrics_text = self._format_metrics(result)
        traces_url = self._build_traces_url(result)

        summary_parts = [
            f"**Experiment**: {result.get('project_name', '')}",
            scores_text,
            f"Baseline: Previous run 🔍 [Traces]({traces_url})",
            f"Avg. case performance: {metrics_text}",
        ]
        return "\n\n".join(summary_parts)

    def _find_previous_result(
        self, result: dict[str, Any], prev_results: EvaluationResults | None
    ) -> dict[str, Any] | None:
        """Find the corresponding previous result by project_name."""
        if not prev_results:
            return None

        project_name = result.get("project_name")
        for prev in prev_results:
            if prev.get("project_name") == project_name:
                return prev
        return None

    def _format_scores(self, result: dict[str, Any], prev_result: dict[str, Any] | None) -> str:
        """Format scores with comparison indicators and baseline comparison."""
        scores_list = []
        for key, value in (result.get("scores") or {}).items():
            score_line = self._format_single_score(key, value, prev_result)
            scores_list.append(score_line)
        return "\n\n".join(scores_list)

    def _format_single_score(self, key: str, value: dict[str, Any], prev_result: dict[str, Any] | None) -> str:
        """Format a single score with comparison indicators."""
        score = f"{(value['score'] * 100):.2f}%" if isinstance(value.get("score"), int | float) else value.get("score")

        baseline_comparison = None
        diff_emoji = "🆕"

        if prev_result:
            baseline_comparison, diff_emoji = self._calculate_score_comparison(key, value, prev_result)

        score_line = f"{diff_emoji} **{key}**: **{score}**"
        if baseline_comparison:
            score_line += f", {baseline_comparison}"
        return score_line

    def _calculate_score_comparison(
        self, key: str, value: dict[str, Any], prev_result: dict[str, Any]
    ) -> tuple[str | None, str]:
        """Calculate comparison metrics between current and previous scores."""
        prev_scores = prev_result.get("scores", {})
        prev_score_data = prev_scores.get(key)

        if not prev_score_data:
            return None, "🆕"

        prev_score = prev_score_data.get("score", 0)
        current_score = value.get("score", 0)
        diff_val = current_score - prev_score

        diff_highlight = "**" if abs(diff_val) > 0.01 else ""
        diff_sign = "+" if diff_val > 0 else ("" if diff_val < 0 else "±")

        # Calculate improvements/regressions (simplified logic)
        improvements = 1 if diff_val > 0.01 else 0
        regressions = 1 if diff_val < -0.01 else 0

        baseline_comparison = f"{diff_highlight}{diff_sign}{(diff_val * 100):.2f}%{diff_highlight} (improvements: {improvements}, regressions: {regressions})"
        diff_emoji = "🟢" if diff_val > 0.01 else ("🔴" if diff_val < -0.01 else "🔵")

        return baseline_comparison, diff_emoji

    def _format_metrics(self, result: dict[str, Any]) -> str:
        """Format key metrics concisely."""
        metrics = result.get("metrics", {})
        if not metrics:
            return "No metrics reported"

        duration = f"⏱️ {metrics['duration']['metric']:.2f} s" if metrics.get("duration") else None
        total_tokens = f"🔢 {int(metrics['total_tokens']['metric'])} tokens" if metrics.get("total_tokens") else None
        cost = f"💵 ${metrics['estimated_cost']['metric']:.4f} in tokens" if metrics.get("estimated_cost") else None

        return ", ".join(filter(None, [duration, total_tokens, cost]))

    def _build_traces_url(self, result: dict[str, Any]) -> str:
        """Build the traces filter URL for the experiment."""
        traces_filter = [
            {
                "key": "ai_experiment_name",
                "value": [result.get("project_name", "")],
                "operator": "exact",
                "type": "event",
            },
            {
                "key": "ai_experiment_id",
                "value": [self.experiment_id],
                "operator": "exact",
                "type": "event",
            },
        ]
        return f"https://us.posthog.com/llm-analytics/traces?filters={urllib.parse.quote(json.dumps(traces_filter))}"


def format_results(
    dataset_id: UUID,
    dataset_name: str,
    experiment_id: str,
    results: EvaluationResults,
    prev_results: EvaluationResults | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Legacy function wrapper for backward compatibility."""
    formatter = ResultsFormatter(dataset_id, dataset_name, experiment_id)
    return formatter.format(results, prev_results)
