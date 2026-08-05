"""
Exported enums for data_catalog.

These are the pure, Django-free types other layers (presentation, information_schema
loaders, MCP tooling) share. Internal-only constants stay in the implementation.
"""

from enum import StrEnum

# The definition kind for an agent-calculated, markdown-step metric (as opposed to an executable
# query definition). Not a posthog.schema query kind — the query runner never executes it; an agent
# follows the steps. JSX object references inside the markdown are a future expansion.
MARKDOWN_DEFINITION_KIND = "MarkdownDefinition"

# Query kinds an executable metric definition may take, split by how they run. Validation maps each
# kind to its posthog.schema model; execution wraps node kinds in a single-series TrendsQuery (they
# have no query runner of their own); the API picks query throttles from the same split.
HOGQL_DEFINITION_KIND = "HogQLQuery"
NODE_DEFINITION_KINDS = ("EventsNode", "ActionsNode", "DataWarehouseNode")
INSIGHT_DEFINITION_KINDS = ("TrendsQuery", "FunnelsQuery")


class MetricStatus(StrEnum):
    """Persisted lifecycle state of a metric. ``drifted`` is computed at read time, never stored."""

    PROPOSED = "proposed"
    APPROVED = "approved"


class CreatedSource(StrEnum):
    """Who authored a catalog entry, for review context."""

    USER = "user"
    AI_GENERATED = "ai_generated"


class CertificationStatus(StrEnum):
    """Human-vouched trust mark on a warehouse table or view."""

    PROPOSED = "proposed"
    CERTIFIED = "certified"
    DEPRECATED = "deprecated"


class RelationshipStatus(StrEnum):
    """Review state of a proposed join between two warehouse tables."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
