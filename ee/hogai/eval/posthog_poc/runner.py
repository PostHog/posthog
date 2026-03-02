from __future__ import annotations

from uuid import uuid4

from .client import PostHogEvalClient
from .types import EvalRunContext, EvalSuite, MetricOutcome
from .utils import serialize_value


async def run_suite(
    suite: EvalSuite,
    client: PostHogEvalClient,
    *,
    distinct_id: str | None = None,
) -> list[dict[str, object]]:
    experiment_id = str(uuid4())
    run_distinct_id = distinct_id or f"ai-eval:{experiment_id}"
    context = EvalRunContext(
        distinct_id=run_distinct_id,
        experiment_id=experiment_id,
        experiment_name=suite.experiment_name,
        evaluation_type=suite.evaluation_type,
        dataset_id=suite.dataset_id,
        posthog_client=client.analytics_client,
    )

    summaries: list[dict[str, object]] = []

    for case in suite.cases:
        input_text = serialize_value(case.input)
        expected_text = serialize_value(case.expected)

        try:
            output = await suite.task(case.input)
        except Exception as exc:
            for metric in suite.metrics:
                client.capture_evaluation(
                    distinct_id=run_distinct_id,
                    evaluation_type=suite.evaluation_type,
                    experiment_id=experiment_id,
                    experiment_name=suite.experiment_name,
                    experiment_item_id=case.id,
                    experiment_item_name=case.name,
                    metric_name=metric.name,
                    metric_version=metric.version,
                    result_type=metric.result_type,
                    status="error",
                    score=None,
                    score_min=None,
                    score_max=None,
                    trace_id=None,
                    input_text=input_text,
                    output_text=None,
                    expected_text=expected_text,
                    reasoning=None,
                    dataset_id=suite.dataset_id,
                    dataset_item_id=case.dataset_item_id,
                    error_code="task_failed",
                    error_message=str(exc),
                )
            client.flush()
            raise

        output_text = serialize_value(output)

        for metric in suite.metrics:
            try:
                outcome = await metric.scorer(case, output, context)
            except Exception as exc:
                outcome = MetricOutcome(
                    status="error",
                    score=None,
                    trace_id=getattr(exc, "trace_id", None),
                    error_code="metric_failed",
                    error_message=str(exc),
                )

            client.capture_evaluation(
                distinct_id=run_distinct_id,
                evaluation_type=suite.evaluation_type,
                experiment_id=experiment_id,
                experiment_name=suite.experiment_name,
                experiment_item_id=case.id,
                experiment_item_name=case.name,
                metric_name=metric.name,
                metric_version=metric.version,
                result_type=metric.result_type,
                status=outcome.status,
                score=outcome.score,
                score_min=metric.score_min,
                score_max=metric.score_max,
                trace_id=outcome.trace_id,
                input_text=input_text,
                output_text=output_text,
                expected_text=expected_text,
                reasoning=outcome.reasoning,
                dataset_id=suite.dataset_id,
                dataset_item_id=case.dataset_item_id,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
            )

            summaries.append(
                {
                    "case_id": case.id,
                    "case_name": case.name,
                    "metric_name": metric.name,
                    "status": outcome.status,
                    "score": outcome.score,
                    "trace_id": outcome.trace_id,
                }
            )

            if outcome.status == "error":
                client.flush()
                raise RuntimeError(
                    f"Metric {metric.name} failed for case {case.id}: {outcome.error_message or outcome.error_code}"
                )

    client.flush()
    return summaries
