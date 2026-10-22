from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "canonical_metric_run": OfflineScorer(kind="boolean", version=UUID("01a15a27-fa96-71e0-b904-13f14079440e")),
    "deprecation_proposed": OfflineScorer(kind="boolean", version=UUID("01a15a28-7a51-7732-838a-34de17d02bbf")),
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15a28-3e1d-7d93-86bb-de7f4e4a5c63")),
    "governed_behavior_correctness": OfflineScorer(
        kind="numeric", version=UUID("01a15a28-0f80-7d6e-b0bb-0573fcb583fa")
    ),
    "metric_create_called": OfflineScorer(kind="boolean", version=UUID("01a15a28-47d2-7eea-ba8a-55266556d782")),
    "metric_description_concise": OfflineScorer(kind="boolean", version=UUID("01a15a28-5017-75a6-b5e5-5ddfe270c02a")),
    "metric_description_quality": OfflineScorer(kind="boolean", version=UUID("01a15a28-5aa6-746d-8d30-bc84b857f15a")),
    "metrics_catalog_before_answer": OfflineScorer(
        kind="boolean", version=UUID("01a15a27-e92c-792a-ab48-24162ed407e9")
    ),
    "metrics_catalog_before_data_discovery": OfflineScorer(
        kind="boolean", version=UUID("01a15a27-f18f-76e9-a67e-0259133b733c")
    ),
    "metrics_catalog_not_queried": OfflineScorer(kind="boolean", version=UUID("01a15a28-0586-7594-9cd5-3f1ff8ca3c06")),
    "metrics_catalog_queried": OfflineScorer(kind="boolean", version=UUID("01a15a27-e0c4-74f7-ae0c-acda47b99ab3")),
    "no_metric_write": OfflineScorer(kind="boolean", version=UUID("01a15a28-30cb-7118-b1c8-9084eba7378e")),
    "proposed_badge": OfflineScorer(kind="boolean", version=UUID("01a15a28-206d-79ea-b231-4bf05e131c80")),
    "semantic_metadata_queried": OfflineScorer(kind="boolean", version=UUID("01a15a28-64d0-787c-af9e-94c4730b8a1c")),
    "semantic_trust_decision_correctness": OfflineScorer(
        kind="numeric", version=UUID("01a15a28-6ded-74ed-a08c-4bfc378b0b5b")
    ),
    "trust_badge": OfflineScorer(kind="boolean", version=UUID("01a15a28-17ed-7638-82e4-d39bd349ce9e")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:data-modeling", "component:data-catalog"),
    )
