from __future__ import annotations

from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from .judge import ChoiceJudgeScorer
from .types import EvalCase, EvalRunContext


@pytest.mark.asyncio
async def eval_choice_judge_uses_posthog_trace_for_llm_call() -> None:
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"choice": "pass", "reasoning": "Looks correct"}'))
            ]
        )
    )

    scorer = ChoiceJudgeScorer(
        metric_name="ticket_summary_quality",
        prompt_template="Output: {{output}}\nExpected: {{expected}}",
        choice_scores={"pass": 1.0, "fail": 0.0},
    )
    case = EvalCase(
        id="case-1",
        name="case",
        input="input",
        expected="expected",
    )
    context = EvalRunContext(
        distinct_id="eval-run-1",
        experiment_id="experiment-1",
        experiment_name="ticket_summary",
        evaluation_type="offline",
        dataset_id=None,
        posthog_client=object(),
    )

    with patch("ee.hogai.eval.posthog_poc.judge.AsyncOpenAI", return_value=fake_openai):
        outcome = await scorer.score(case, "output", context)

    assert outcome.trace_id is not None
    call_kwargs = fake_openai.chat.completions.create.await_args.kwargs
    assert call_kwargs["posthog_trace_id"] == outcome.trace_id
    assert call_kwargs["posthog_distinct_id"] == "eval-run-1"
    assert call_kwargs["posthog_properties"]["$ai_metric_name"] == "ticket_summary_quality"
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert call_kwargs["response_format"]["json_schema"]["schema"]["properties"]["choice"]["enum"] == ["pass", "fail"]
