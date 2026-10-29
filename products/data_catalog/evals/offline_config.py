from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "analysis_diligence": OfflineScorer(kind="numeric", version=UUID("01a1893a-ef5a-7582-b8a4-fdac6ccc44ed")),
    "annotations_read": OfflineScorer(kind="boolean", version=UUID("01a1893a-9207-7bdc-93c9-24c0fc22ca72")),
    "anomaly_flagged": OfflineScorer(kind="boolean", version=UUID("01a1893a-ba5d-791c-861b-3051e53e5251")),
    "answer_correctness": OfflineScorer(kind="numeric", version=UUID("01a1893a-f6d4-7568-9da0-0ea2c4a9fb96")),
    "answer_table_queried": OfflineScorer(kind="boolean", version=UUID("01a16878-7805-7322-8f32-f1f5f8f36428")),
    "answer_value_stated": OfflineScorer(kind="boolean", version=UUID("01a16878-7117-7e4a-b1d0-421050827937")),
    "canonical_metric_run": OfflineScorer(kind="boolean", version=UUID("01a15a27-fa96-71e0-b904-13f14079440e")),
    "catalog_search_used": OfflineScorer(kind="boolean", version=UUID("01a1893a-2359-7da2-9fc1-31e2d533c393")),
    "claim_measured": OfflineScorer(kind="boolean", version=UUID("01a1893a-9950-7589-b838-312317553fdb")),
    "context_applied": OfflineScorer(kind="boolean", version=UUID("01a1893a-b26b-7129-8484-d570eab3476b")),
    "deprecation_proposed": OfflineScorer(kind="boolean", version=UUID("01a15a28-7a51-7732-838a-34de17d02bbf")),
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15a28-3e1d-7d93-86bb-de7f4e4a5c63")),
    "first_seen_checked": OfflineScorer(kind="boolean", version=UUID("01a1893a-aa6c-7c37-b64a-cf760dff58e6")),
    "governed_behavior_correctness": OfflineScorer(
        kind="numeric", version=UUID("01a15a28-0f80-7d6e-b0bb-0573fcb583fa")
    ),
    "hypothesis_evidence_queried": OfflineScorer(kind="boolean", version=UUID("01a1893a-a1ae-770b-b78b-a9293065ecef")),
    "metric_create_called": OfflineScorer(kind="boolean", version=UUID("01a15a28-47d2-7eea-ba8a-55266556d782")),
    "metric_describe_before_adapted_sql": OfflineScorer(
        kind="boolean", version=UUID("01a1893a-3bfa-7dd3-86e5-63aa1912f6ae")
    ),
    "metric_describe_called": OfflineScorer(kind="boolean", version=UUID("01a1893a-80bf-73d7-9bef-685410a5ecc0")),
    "metric_description_concise": OfflineScorer(kind="boolean", version=UUID("01a15a28-5017-75a6-b5e5-5ddfe270c02a")),
    "metric_description_quality": OfflineScorer(kind="boolean", version=UUID("01a15a28-5aa6-746d-8d30-bc84b857f15a")),
    "metric_found": OfflineScorer(kind="boolean", version=UUID("01a1893a-1b14-795f-ac5c-ebb4c244e0bb")),
    "metrics_catalog_before_answer": OfflineScorer(
        kind="boolean", version=UUID("01a15a27-e92c-792a-ab48-24162ed407e9")
    ),
    "metrics_catalog_before_data_discovery": OfflineScorer(
        kind="boolean", version=UUID("01a15a27-f18f-76e9-a67e-0259133b733c")
    ),
    "metrics_catalog_not_queried": OfflineScorer(kind="boolean", version=UUID("01a15a28-0586-7594-9cd5-3f1ff8ca3c06")),
    "metrics_catalog_queried": OfflineScorer(kind="boolean", version=UUID("01a15a27-e0c4-74f7-ae0c-acda47b99ab3")),
    "no_data_sql_run": OfflineScorer(kind="boolean", version=UUID("01a1893a-334a-752a-97a7-7b9ea3dbce0b")),
    "no_metric_write": OfflineScorer(kind="boolean", version=UUID("01a15a28-30cb-7118-b1c8-9084eba7378e")),
    "proposed_badge": OfflineScorer(kind="boolean", version=UUID("01a15a28-206d-79ea-b231-4bf05e131c80")),
    "query_terms_used": OfflineScorer(kind="numeric", version=UUID("01a1893a-d7ed-7587-91b1-9c6ff5c20205")),
    "run_override_used": OfflineScorer(kind="boolean", version=UUID("01a1893a-2bb8-7f8d-a19e-94269b7e6fca")),
    "semantic_layer_answer": OfflineScorer(kind="numeric", version=UUID("01a1893a-e78b-72c6-90fc-6c4310d88262")),
    "semantic_metadata_queried": OfflineScorer(kind="boolean", version=UUID("01a15a28-64d0-787c-af9e-94c4730b8a1c")),
    "semantic_trust_decision_correctness": OfflineScorer(
        kind="numeric", version=UUID("01a15a28-6ded-74ed-a08c-4bfc378b0b5b")
    ),
    "sentinel_absent": OfflineScorer(kind="boolean", version=UUID("01a1893a-448a-72e4-abed-3b1d03271183")),
    "sources_avoided": OfflineScorer(kind="boolean", version=UUID("01a1893a-4d81-73de-8a6e-687277f05729")),
    "sources_consulted": OfflineScorer(kind="numeric", version=UUID("01a1893a-deaa-71b2-ab5a-818ddecb5b4c")),
    "surfaces_all_findings": OfflineScorer(kind="boolean", version=UUID("01a1558f-ad52-7b81-8a93-d7e602bf0125")),
    "table_inspected": OfflineScorer(kind="boolean", version=UUID("01a1893a-5564-7dfa-8d1d-e2d15bb8808c")),
    "trust_badge": OfflineScorer(kind="boolean", version=UUID("01a15a28-17ed-7638-82e4-d39bd349ce9e")),
    "verified_before_explaining": OfflineScorer(kind="boolean", version=UUID("01a1893a-890b-7cf2-ab58-28fd0442f5c8")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:data-modeling", "component:data-catalog"),
    )
