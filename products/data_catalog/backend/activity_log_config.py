FIELD_EXCLUSIONS = {
    "Metric": [
        # Derived/throttled fields, not user-meaningful change diffs.
        "last_run_at",
        "source_insight_query_hash",
        "referenced_table_names",
        "embedding",
        "embedding_model",
        "embedding_text_hash",
    ],
}
