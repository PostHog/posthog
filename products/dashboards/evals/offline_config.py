from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15a27-ce66-7f1a-babd-0e1423882e9b")),
    "saved_dashboard_contents": OfflineScorer(kind="boolean", version=UUID("01a15a27-c451-7557-9bca-c968f6358a91")),
    "sql_tiles_follow_dashboard_date_range": OfflineScorer(
        kind="numeric", version=UUID("01a15a27-d794-74b3-8822-063a74a674fd")
    ),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:product-analytics", "component:dashboards"),
    )
