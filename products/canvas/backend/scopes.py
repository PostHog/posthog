"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="canvas",
        name="Canvas",
        plural="canvases",
        description="Canvases, the agent-built apps filed into channels, including their source, versions, publishing, and state.",
        group="Product analytics",
    ),
)
