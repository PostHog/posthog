from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import uuid4

from django.conf import settings

from posthoganalytics.ai.openai import AsyncOpenAI

from .types import EvalCase, EvalMetric, EvalRunContext, MetricOutcome
from .utils import parse_json_object, render_prompt_template, serialize_value

Transform = Callable[[Any], Any]


def _identity(value: Any) -> Any:
    return value


class JudgeScorerError(RuntimeError):
    def __init__(self, message: str, *, trace_id: str):
        super().__init__(message)
        self.trace_id = trace_id


@dataclass(frozen=True)
class ChoiceJudgeScorer:
    metric_name: str
    prompt_template: str
    choice_scores: Mapping[str, float]
    model: str = "gpt-4.1"
    version: str = "1"
    prepare_input: Transform = _identity
    prepare_output: Transform = _identity
    prepare_expected: Transform = _identity
    score_if_both_missing: float | None = None
    score_if_one_missing: float | None = None

    def as_metric(
        self,
        *,
        result_type: Literal["binary", "numeric"] = "binary",
        score_min: float | None = 0,
        score_max: float | None = 1,
    ) -> EvalMetric:
        return EvalMetric(
            name=self.metric_name,
            version=self.version,
            result_type=result_type,
            score_min=score_min,
            score_max=score_max,
            scorer=self.score,
        )

    async def score(self, case: EvalCase[Any, Any], output: Any, context: EvalRunContext) -> MetricOutcome:
        prepared_output = self.prepare_output(output)
        prepared_expected = self.prepare_expected(case.expected)

        if prepared_output is None and prepared_expected is None and self.score_if_both_missing is not None:
            return MetricOutcome(status="ok", score=self.score_if_both_missing)
        if (prepared_output is None) != (prepared_expected is None) and self.score_if_one_missing is not None:
            return MetricOutcome(status="ok", score=self.score_if_one_missing)

        input_text = serialize_value(self.prepare_input(case.input)) or ""
        output_text = serialize_value(prepared_output) or ""
        expected_text = serialize_value(prepared_expected) or ""
        trace_id = str(uuid4())
        try:
            client = AsyncOpenAI(posthog_client=context.posthog_client, base_url=settings.OPENAI_BASE_URL)
            response = await client.chat.completions.create(  # type: ignore[call-overload]
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._build_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": render_prompt_template(
                            self.prompt_template,
                            input_text=input_text,
                            output_text=output_text,
                            expected_text=expected_text,
                        ),
                    },
                ],
                response_format=cast(Any, self._build_response_format()),
                posthog_trace_id=trace_id,
                posthog_distinct_id=context.distinct_id,
                posthog_properties={
                    "$ai_experiment_id": context.experiment_id,
                    "$ai_experiment_name": context.experiment_name,
                    "$ai_experiment_item_id": case.id,
                    "$ai_experiment_item_name": case.name,
                    "$ai_metric_name": self.metric_name,
                    "$ai_metric_version": self.version,
                    "$ai_span_name": f"judge:{self.metric_name}",
                },
            )

            content = None
            if response.choices:
                content = response.choices[0].message.content

            parsed = parse_json_object(content)
            choice = parsed.get("choice")
            if not isinstance(choice, str):
                raise ValueError(f"Judge response missing string 'choice': {parsed}")
            if choice not in self.choice_scores:
                raise ValueError(f"Judge returned unsupported choice '{choice}' for metric {self.metric_name}")

            reasoning = parsed.get("reasoning")
            if reasoning is not None and not isinstance(reasoning, str):
                raise ValueError(f"Judge response had invalid reasoning for metric {self.metric_name}: {parsed}")

            return MetricOutcome(
                status="ok",
                score=self.choice_scores[choice],
                reasoning=reasoning,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise JudgeScorerError(str(exc), trace_id=trace_id) from exc

    def _build_system_prompt(self) -> str:
        choices = ", ".join(self.choice_scores.keys())
        return (
            "You are an evaluator.\n"
            f"Choose exactly one label from: {choices}.\n"
            "Use the provided JSON schema.\n"
            '"reasoning" must be a short explanation.'
        )

    def _build_response_format(self) -> dict[str, Any]:
        schema_name = re.sub(r"[^a-zA-Z0-9_]+", "_", self.metric_name).strip("_") or "judge_response"
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "choice": {
                            "type": "string",
                            "enum": list(self.choice_scores.keys()),
                        },
                        "reasoning": {
                            "type": "string",
                        },
                    },
                    "required": ["choice", "reasoning"],
                    "additionalProperties": False,
                },
            },
        }
