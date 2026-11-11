"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="ai_observability_clusters",
        name="Cluster",
        plural="clusters",
        description="Clusters of similar AI traces, including clustering runs, jobs, and their event filter settings.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-observability/clusters",
    ),
    ScopeDoc(
        object="dataset",
        name="Dataset",
        plural="datasets",
        description="Datasets for AI evals, including their items, revisions, archiving, and exports.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-evals/datasets",
    ),
    ScopeDoc(
        object="evaluation",
        name="Evaluation",
        plural="evaluations",
        description="LLM evaluations, including their runs, scores, reports, backfills over past data, and offline evals.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-evals",
    ),
    ScopeDoc(
        object="llm_analytics",
        name="AI observability",
        plural="AI observability",
        description="AI observability traces, trace reviews, review queues, scores, summaries, and evaluation settings.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-observability",
    ),
    ScopeDoc(
        object="llm_playground",
        name="LLM playground",
        plural="LLM playground",
        description="Listing models and running prompts in the LLM playground.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-observability/playground",
    ),
    ScopeDoc(
        object="llm_prompt",
        name="LLM prompt",
        plural="LLM prompts",
        description="LLM prompts in prompt management, including versions, labels, and fetching prompts by name.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/prompt-management",
    ),
    ScopeDoc(
        object="llm_provider_key",
        name="LLM provider key",
        plural="LLM provider keys",
        description="LLM provider API keys used for evaluations and the playground, including validating them.",
        group="LLM & MCP analytics",
    ),
    ScopeDoc(
        object="offline_evaluation_ingestion",
        name="Offline evaluation ingestion",
        plural="offline evaluation uploads",
        description="Creating offline evaluation experiments, uploading their results, and marking them completed or failed.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-evals/offline-evals",
        actions=("write",),
    ),
    ScopeDoc(
        object="tagger",
        name="Tagger",
        plural="taggers",
        description="Taggers that automatically label your AI generations, including testing tagger code on sample events.",
        group="LLM & MCP analytics",
        docs_url="https://posthog.com/docs/ai-evals/taggers",
    ),
)
