"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="batch_export",
        name="Batch export",
        plural="batch exports",
        description="Batch exports to destinations like S3, BigQuery, and Snowflake, including runs, backfills, and file downloads.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/data-pipelines/batch-exports",
    ),
)
