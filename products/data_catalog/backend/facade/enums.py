"""
Exported enums for data_catalog.

These are the pure, Django-free types other layers (presentation, information_schema
loaders, MCP tooling) share. Internal-only constants stay in the implementation.
"""

from enum import StrEnum

from posthog.enums import LabeledStrEnum

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


# Gates every catalog usage surface. While it is off, the usage endpoints answer 404.
USAGE_FLAG_KEY = "data-catalog-usage"

# The `source` that scheduled agents (scouts) stamp on the run event and on `$ai_generation`.
# A scout can run one metric many times a day, so usage counts keep scouts apart from every
# headline number.
SCOUT_SOURCE = "self_driving"


class UsageSnapshotStatus(LabeledStrEnum):
    """Lifecycle of one usage scan. A snapshot row is written once per scan and never reused."""

    COMPUTING = "computing", "Computing"
    DONE = "done", "Done"
    ERROR = "error", "Error"


class UsageSection(StrEnum):
    """One section of a usage snapshot payload. Each scan step writes one section."""

    METRIC_RUNS = "metric_runs"
    ADJUSTED_RUNS = "adjusted_runs"
    TOPICS = "topics"
    UNCOVERED = "uncovered"


class JudgeRelation(StrEnum):
    """What the judge decided about an agent query that resembles a catalog metric."""

    SERVES = "serves"
    SLICE = "slice"
    DIFFERENT = "different"


class FetchOutcome(StrEnum):
    """Whether the agent consulted the catalog before it re-derived a metric in SQL."""

    ADAPTED = "adapted"
    MISSED = "missed"
    SILENT = "silent"


class ShapeOutcome(StrEnum):
    """How a recurring query shape relates to the catalog."""

    COVERED = "covered"
    SLICE = "slice"
    UNCOVERED = "uncovered"
