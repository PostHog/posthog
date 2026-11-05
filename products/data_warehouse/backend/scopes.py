"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="warehouse_table",
        name="Warehouse table",
        plural="warehouse tables",
        description="Data warehouse tables, including their schemas, file uploads, column descriptions, and column statistics.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/data-warehouse",
    ),
    ScopeDoc(
        object="warehouse_view",
        name="Warehouse view",
        plural="warehouse views",
        description="Data warehouse views and joins, including materialization runs, lineage, folders, and saved expressions.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/data-warehouse/views",
    ),
)
