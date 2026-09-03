"""HogQL surface for the AEO citation record.

Exposed as `system.aeo_citation_checks` so insights, the SQL editor, the query
API, and MCP can all read the record, while the only write path stays the
backend runner.
"""

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable

aeo_citation_checks: PostgresTable = PostgresTable(
    name="aeo_citation_checks",
    postgres_table_name="posthog_aeo_citation_check",
    access_scope="web_analytics",
    description=(
        "AEO citation checks: one row per prompt x answer engine per run, recording whether the "
        "team's target domain was cited. Written only by the citation runner."
    ),
    fields={
        "id": UUIDDatabaseField(name="id", description="Check id."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the check ran."),
        "run_id": UUIDDatabaseField(name="run_id", description="Groups every check from one runner pass."),
        "prompt_id": UUIDDatabaseField(name="prompt_id", description="Prompt that ran; joins to the prompt set."),
        "prompt_text": StringDatabaseField(name="prompt_text", description="The question as it ran."),
        "prompt_source": StringDatabaseField(
            name="prompt_source", description="Where the prompt came from: 'imported' or 'manual'."
        ),
        "prompt_hash": StringDatabaseField(
            name="prompt_hash", description="SHA-256 of the normalized prompt; stable join key across runs."
        ),
        "engine": StringDatabaseField(
            name="engine", description="Answer engine: claude-web-search, openai-web-search, or exa-answer."
        ),
        "model": StringDatabaseField(name="model", description="Engine model that answered."),
        "check_failed": BooleanDatabaseField(
            name="check_failed",
            description="The engine did not answer, so the row is not evidence that citations disappeared.",
        ),
        "error": StringDatabaseField(name="error", nullable=True, description="Why the check failed, when it did."),
        "cited": BooleanDatabaseField(
            name="cited", description="A target-domain URL appears in the answer's citations."
        ),
        "num_citations": IntegerDatabaseField(name="num_citations", description="How many URLs the answer cited."),
        "target_best_position": IntegerDatabaseField(
            name="target_best_position",
            nullable=True,
            description="1-based position of the first target-domain URL in the citation list.",
        ),
        "cited_urls": StringJSONDatabaseField(
            name="cited_urls", description="JSON array of URLs the answer cites, in first-mention order."
        ),
        "retrieved_urls": StringJSONDatabaseField(
            name="retrieved_urls", description="JSON array of URLs the engine retrieved but did not necessarily cite."
        ),
        "search_queries": StringJSONDatabaseField(
            name="search_queries", description="JSON array of search queries the engine issued."
        ),
        "target_urls": StringJSONDatabaseField(
            name="target_urls", description="JSON array of cited URLs on a target domain."
        ),
        "top_cited_domains": StringJSONDatabaseField(
            name="top_cited_domains", description="JSON array of distinct hosts across the cited URLs."
        ),
        "cost_usd": FloatDatabaseField(
            name="cost_usd", nullable=True, description="Engine-reported cost, where the engine reports one."
        ),
        "gateway_trace_id": StringDatabaseField(
            name="gateway_trace_id",
            nullable=True,
            description="Joins to the gateway's $ai_generation event, which carries token and web-search cost.",
        ),
    },
)
