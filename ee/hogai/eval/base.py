import os
import json
import asyncio
import tempfile
from collections.abc import Sequence
from functools import partial

import pytest

from braintrust import EvalAsync, EvalCase, Metadata, init_logger
from braintrust.framework import EvalData, EvalResultWithSummary, EvalScorer, EvalTask, Input, Output

from posthog.models.utils import uuid7

from ee.hogai.eval.schema import DatasetInput


async def _filter_data(data: EvalData[Input, Output], case_filter: str | None = None):
    # Resolve async data
    if asyncio.iscoroutine(data):
        # Async iterator
        if hasattr(data, "__aiter__"):
            data = [case async for case in data]
        # asyncio.iscoroutine may return True for sync generators
        elif hasattr(data, "__iter__"):
            data = list(data)
        # Regular awaitable
        else:
            data = await data
    cases = []
    for case in data:  # type: ignore
        if not isinstance(case, EvalCase):
            cases.append(case)
            continue

        # Reset trace IDs for DatasetInput, so we use distinct IDs instead
        if os.getenv("EVAL_MODE") == "offline" and isinstance(case.input, DatasetInput):
            # Mutating the input in place is intentional here. Just avoiding copying the whole object.
            case.input.trace_id = str(uuid7())

        # Filter by --case <eval_case_name_part> pytest flag
        if case_filter:
            if case_filter in str(case.input):
                cases.append(case)
        else:
            cases.append(case)

    return cases


async def BaseMaxEval(
    experiment_name: str,
    data: EvalData[Input, Output],
    task: EvalTask[Input, Output],
    scores: Sequence[EvalScorer[Input, Output]],
    pytestconfig: pytest.Config,
    metadata: Metadata | None = None,
    is_public: bool = False,
    no_send_logs: bool = True,
):
    if is_public and not no_send_logs:
        # We need to specify a separate project for each MaxEval() suite for comparison to baseline to work
        # That's the way Braintrust folks recommended - Braintrust projects are much more lightweight than PostHog ones
        project_name = f"max-ai-{experiment_name}"
        init_logger(project_name)
    else:
        project_name = experiment_name

    case_filter = pytestconfig.option.eval

    timeout = 60 * 8  # 8 minutes
    if os.getenv("EVAL_MODE") == "offline":
        timeout = 60 * 60  # 1 hour

    result = await EvalAsync(
        project_name,
        data=await _filter_data(data, case_filter=case_filter),
        task=task,
        scores=scores,
        timeout=timeout,
        max_concurrency=100,
        is_public=is_public,
        no_send_logs=no_send_logs,
        metadata=metadata,
    )

    # If we're running in the offline mode and the test case marked as public, the pipeline must completely fail.
    if os.getenv("EVAL_MODE") == "offline" and is_public:
        raise RuntimeError("Evaluation cases must be private when EVAL_MODE is set to offline.")

    if os.getenv("EXPORT_EVAL_RESULTS"):
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")

    _print_eval_stats(experiment_name, result)

    return result


def _serialize_eval_result(eval_result) -> dict:
    """Serialize an EvalResult to a JSON-safe dict, handling non-serializable fields."""
    result: dict = {
        "input": str(eval_result.input),
        "output": str(eval_result.output),
        "scores": eval_result.scores,
    }
    if eval_result.expected is not None:
        result["expected"] = str(eval_result.expected)
    if eval_result.metadata is not None:
        result["metadata"] = eval_result.metadata
    if eval_result.error is not None:
        result["error"] = str(eval_result.error)
    if eval_result.exc_info is not None:
        result["exc_info"] = eval_result.exc_info
    return result


def _dump_eval_results(experiment_name: str, result: EvalResultWithSummary) -> str:
    """Dump full untruncated eval results to a temporary JSON file. Returns the file path."""
    dump = {
        "experiment_name": experiment_name,
        "project_name": result.summary.project_name,
        "scores_summary": {
            name: {
                "score": s.score,
                "diff": s.diff,
                "improvements": s.improvements,
                "regressions": s.regressions,
            }
            for name, s in result.summary.scores.items()
        },
        "results": [_serialize_eval_result(r) for r in result.results],
    }

    dump_file = tempfile.NamedTemporaryFile(
        prefix=f"eval_{experiment_name}_",
        suffix=".json",
        delete=False,
        mode="w",
    )
    json.dump(dump, dump_file, indent=2, default=str)
    dump_file.close()
    return dump_file.name


def _print_eval_stats(experiment_name: str, result: EvalResultWithSummary) -> None:
    """Print eval stats to the console so agents can parse them."""
    summary = result.summary
    results = result.results

    # Dump full results to a temp file for detailed inspection
    dump_path = _dump_eval_results(experiment_name, result)

    lines: list[str] = []
    lines.append("")
    lines.append(f"{'=' * 60}")
    lines.append(f"EVAL STATS: {experiment_name} ({len(results)} cases)")
    lines.append(f"Full results: {dump_path}")
    lines.append(f"{'=' * 60}")

    # Score summary
    if summary.scores:
        lines.append("")
        lines.append("Score Summary:")
        for score_summary in summary.scores.values():
            pct = f"{score_summary.score * 100:.1f}%"
            diff_str = ""
            if score_summary.diff is not None:
                sign = "+" if score_summary.diff > 0 else ""
                diff_str = f" ({sign}{score_summary.diff * 100:.1f}%)"
            imp_reg = ""
            if score_summary.improvements is not None or score_summary.regressions is not None:
                imp_reg = (
                    f" [{score_summary.improvements or 0} improvements, {score_summary.regressions or 0} regressions]"
                )
            lines.append(f"  {score_summary.name}: {pct}{diff_str}{imp_reg}")

    # Separate failed and passed cases
    failed = []
    passed = []
    for eval_result in results:
        has_failure = eval_result.error is not None or any(
            v is not None and v < 1.0 for v in eval_result.scores.values()
        )
        if has_failure:
            failed.append(eval_result)
        else:
            passed.append(eval_result)

    # Failed cases with full details for debugging
    if failed:
        lines.append("")
        lines.append(f"Failed Cases ({len(failed)}/{len(results)}):")
        for eval_result in failed:
            score_parts = []
            for score_name, score_val in eval_result.scores.items():
                if score_val is not None:
                    score_parts.append(f"{score_name}={score_val:.2f}")
                else:
                    score_parts.append(f"{score_name}=N/A")
            scores_str = ", ".join(score_parts)
            lines.append(f"  - Input: {eval_result.input}")
            lines.append(f"    Output: {eval_result.output}")
            if eval_result.expected is not None:
                lines.append(f"    Expected: {eval_result.expected}")
            lines.append(f"    Scores: {scores_str}")
            if eval_result.error:
                lines.append(f"    Error: {eval_result.error}")

    # Passed cases (condensed)
    if passed:
        lines.append("")
        lines.append(f"Passed Cases ({len(passed)}/{len(results)}):")
        for eval_result in passed:
            input_str = str(eval_result.input)
            if len(input_str) > 80:
                input_str = input_str[:77] + "..."
            lines.append(f"  - {input_str}")

    lines.append(f"{'=' * 60}")
    lines.append("")

    print("\n".join(lines))  # noqa: T201


MaxPublicEval = partial(BaseMaxEval, is_public=True, no_send_logs=False)
"""Evaluation case that is publicly accessible."""

MaxPrivateEval = partial(BaseMaxEval, is_public=False, no_send_logs=True)
"""Evaluation case is not accessible publicly."""
