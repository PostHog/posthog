from posthog.api.routing import RouterRegistry
from posthog.settings import CLOUD_DEPLOYMENT, DEBUG, TEST

from products.ai_observability.backend.api import (
    AIObservabilityClusteringRunViewSet,
    AIObservabilityOfflineEvaluationsViewSet,
    AIObservabilitySummarizationViewSet,
    AIObservabilityTextReprViewSet,
    AIObservabilityTranslateViewSet,
    ClusteringConfigViewSet,
    ClusteringJobViewSet,
    DatasetItemViewSet,
    DatasetViewSet,
    EvaluationConfigViewSet,
    EvaluationReportViewSet,
    EvaluationRunViewSet,
    EvaluationViewSet,
    LLMEvaluationSummaryViewSet,
    LLMModelsViewSet,
    LLMProviderKeyValidationViewSet,
    LLMProviderKeyViewSet,
    LLMProxyViewSet,
    ParserRecipeViewSet,
    PersonalSpendViewSet,
    ReviewQueueItemViewSet,
    ReviewQueueViewSet,
    ScoreDefinitionViewSet,
    TaggerViewSet,
    TraceReviewViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"llm_proxy", LLMProxyViewSet, "llm_proxy")
    # @me/spend is only useful where billing data is available; mirrors the
    # CLOUD/DEBUG/TEST gate the registration carried inline.
    if CLOUD_DEPLOYMENT == "US" or DEBUG or TEST:
        routers.root.register(r"llm_analytics/@me/spend", PersonalSpendViewSet, "personal_spend")

    routers.projects.register(
        r"llm_analytics/parser_recipes", ParserRecipeViewSet, "project_llm_analytics_parser_recipes", ["team_id"]
    )
    routers.register_legacy_dual_route(r"datasets", DatasetViewSet, "environment_datasets", ["team_id"])
    routers.register_legacy_dual_route(r"dataset_items", DatasetItemViewSet, "environment_dataset_items", ["team_id"])
    routers.register_legacy_dual_route(r"evaluations", EvaluationViewSet, "project_evaluations", ["team_id"])
    routers.register_legacy_dual_route(r"taggers", TaggerViewSet, "project_taggers", ["team_id"])
    routers.register_legacy_dual_route(r"evaluation_runs", EvaluationRunViewSet, "project_evaluation_runs", ["team_id"])
    routers.register_legacy_dual_route(
        r"llm_analytics/text_repr", AIObservabilityTextReprViewSet, "project_llm_analytics_text_repr", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/summarization",
        AIObservabilitySummarizationViewSet,
        "project_llm_analytics_summarization",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/evaluation_summary",
        LLMEvaluationSummaryViewSet,
        "project_llm_analytics_evaluation_summary",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/translate", AIObservabilityTranslateViewSet, "project_llm_analytics_translate", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/provider_keys", LLMProviderKeyViewSet, "project_llm_analytics_provider_keys", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/provider_key_validations",
        LLMProviderKeyValidationViewSet,
        "project_llm_analytics_provider_key_validations",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/models", LLMModelsViewSet, "project_llm_analytics_models", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/evaluation_config",
        EvaluationConfigViewSet,
        "project_llm_analytics_evaluation_config",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/clustering_runs",
        AIObservabilityClusteringRunViewSet,
        "project_llm_analytics_clustering_runs",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/clustering_config",
        ClusteringConfigViewSet,
        "project_llm_analytics_clustering_config",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/clustering_jobs", ClusteringJobViewSet, "project_llm_analytics_clustering_jobs", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/offline_evaluations",
        AIObservabilityOfflineEvaluationsViewSet,
        "project_llm_analytics_offline_evaluations",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/review_queue_items",
        ReviewQueueItemViewSet,
        "project_llm_analytics_review_queue_items",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/review_queues", ReviewQueueViewSet, "project_llm_analytics_review_queues", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/score_definitions",
        ScoreDefinitionViewSet,
        "project_llm_analytics_score_definitions",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/trace_reviews", TraceReviewViewSet, "project_llm_analytics_trace_reviews", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"llm_analytics/evaluation_reports",
        EvaluationReportViewSet,
        "project_llm_analytics_evaluation_reports",
        ["team_id"],
    )
