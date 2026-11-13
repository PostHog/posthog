# HDBSCAN requires at least five items per group and disallows a single cluster by default.
MIN_CLUSTERING_ITEMS = 10
TRACE_LOOKBACK_DAYS = 7
EVALUATION_LOOKBACK_DAYS = 3
FIRST_RUN_SAMPLE_LIMIT = 100
FIRST_RUN_WORKFLOW = "ai-observability-clustering-first-run"


def clustering_lookback_days(analysis_level: str) -> int:
    return EVALUATION_LOOKBACK_DAYS if analysis_level == "evaluation" else TRACE_LOOKBACK_DAYS
