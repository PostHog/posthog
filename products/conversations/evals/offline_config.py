from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "citation_precision": OfflineScorer(kind="numeric", version=UUID("01a15a27-9528-7df7-89dc-717fdb43d339")),
    "clarifying_question": OfflineScorer(kind="boolean", version=UUID("01a15a27-ba72-7483-8369-8a46861c680f")),
    "cost": OfflineScorer(kind="boolean", version=UUID("01a15a27-a827-7494-a247-daf97f55b7fd")),
    "forbidden_claims": OfflineScorer(kind="boolean", version=UUID("01a15a27-9d10-7260-ace1-335661c5bfdc")),
    "grounding": OfflineScorer(kind="boolean", version=UUID("01a15a27-b117-7e00-aefd-30eb5f5b7e4a")),
    "outcome_match": OfflineScorer(kind="boolean", version=UUID("01a15a27-8bab-7c0e-8a33-d9ac6327874e")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:conversations", "component:conversations"),
    )
