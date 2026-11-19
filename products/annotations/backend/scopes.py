"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="annotation",
        name="Annotation",
        plural="annotations",
        description="Annotations on charts, plus the change feed of feature flag, experiment, release, and annotation edits.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/data/annotations",
    ),
)
