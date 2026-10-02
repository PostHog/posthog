from products.ai_observability.evals.offline_scorers import OfflineAnalysisCorrectness
from products.ai_observability.evals.offline_seeders import (
    BASELINE_NAME,
    CANDIDATE_NAME,
    CHANGED_RULE_NAME,
    seed_offline_comparison,
)
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall, RequiredToolCall


async def eval_offline_evaluations(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-offline-evaluations-cli",
        cases=[
            SandboxedEvalCase(
                name="compare_runs_with_missing_results",
                prompt=f'Compare "{BASELINE_NAME}" and "{CANDIDATE_NAME}". Did the candidate improve? Explain the evidence and coverage.',
                setup=seed_offline_comparison,
                expected={
                    "offline_analysis_correctness": (
                        "Baseline passes 2/3 successful results (~66.7%); candidate passes 2/2 (100%). "
                        "Each run has one evaluator error; candidate also has one missing result among four items. "
                        "Mention reduced successful coverage and do not claim the application definitively improved "
                        "from pass rate alone. Both use the same original scorer version and dataset revision."
                    )
                },
            ),
            SandboxedEvalCase(
                name="explain_case_failure",
                prompt=f'Why did case-2 fail in "{BASELINE_NAME}"? Inspect the actual input, output, and scorer reasoning.',
                setup=seed_offline_comparison,
                expected={
                    "offline_analysis_correctness": (
                        "The input asks for 2 + 2, the application answered 5, and expected output is 4. "
                        "The scorer reason confirms that mismatch. Execution status ok means the evaluator ran "
                        "successfully; the false score fails the original version's true-passes rule. "
                        "Do not reinterpret it using the current version's reversed polarity or call it an evaluator error."
                    )
                },
            ),
            SandboxedEvalCase(
                name="distinguish_changed_scorer_rules",
                prompt=f'Compare "{BASELINE_NAME}" and "{CHANGED_RULE_NAME}". Does the score change show an application regression?',
                setup=seed_offline_comparison,
                expected={
                    "offline_analysis_correctness": (
                        "The application and dataset revisions are the same. The scorer version changed boolean "
                        "polarity from true passing to true failing. Identical successful raw scores yield 2/3 "
                        "versus 1/3 passing. Explain the grading-rule change, keep versions separate, and do not "
                        "attribute this difference to an application regression."
                    )
                },
            ),
        ],
        scorers=[
            OfflineAnalysisCorrectness(),
            RequiredToolCall(
                {
                    "llma-offline-experiment-scorer-summary-list",
                    "llma-offline-experiment-item-result-list",
                    "llma-offline-scorer-history",
                },
                name="read_offline_results",
            ),
            NoToolCall(
                {
                    "llma-offline-experiment-create",
                    "llma-offline-experiment-upload",
                    "llma-offline-experiment-complete",
                    "llma-offline-experiment-fail",
                },
                name="kept_analysis_read_only",
            ),
        ],
        ctx=ctx,
    )
