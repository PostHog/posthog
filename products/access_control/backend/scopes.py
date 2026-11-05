"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="access_control",
        name="Access control",
        plural="access controls",
        description="Who can access each resource, including project-wide defaults, per-resource rules, and property-level rules.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/settings/access-control",
    ),
)
