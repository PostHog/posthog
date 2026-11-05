"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="autoresearch",
        name="Autoresearch",
        plural="autoresearch pipelines",
        description="Autoresearch prediction pipelines, their training runs, models, daily scoring runs, and steering suggestions.",
        group="AI & context management tools",
    ),
)
