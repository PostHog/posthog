"""HogQL surface for the AEO citation record and brand catalog.

Exposed as `system.aeo_citation_checks` and `system.aeo_brands` so insights, the
SQL editor, the query API, and MCP can all read them, while the only write paths
stay the backend runner and the brands API.
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
    # No access_scope: AEO has no RBAC resource behind it — no viewset, no per-row
    # grants — so there is nothing for object-level gating to resolve against, the
    # way cohorts, exports and teams are also unscoped. Team isolation still applies
    # through the team_id predicate every system table carries.
    access_scope=None,
    description=(
        "AEO citation checks: one row per prompt x answer engine per run, recording whether the "
        "team's target domain was cited. Written only by the citation runner."
    ),
    fields={
        "id": UUIDDatabaseField(name="id", description="Check id."),
        "team_id": IntegerDatabaseField(name="team_id", hidden=True),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the check ran."),
        "run_id": UUIDDatabaseField(name="run_id", description="Groups every check from one runner pass."),
        "prompt_id": UUIDDatabaseField(name="prompt_id", description="Prompt that ran; joins to the prompt set."),
        "prompt_text": StringDatabaseField(name="prompt_text", description="The question as it ran."),
        "prompt_source": StringDatabaseField(
            name="prompt_source", description="Where the prompt came from: 'imported' or 'manual'."
        ),
        "prompt_topic": StringDatabaseField(
            name="prompt_topic", description="Topic the prompt belonged to when it ran; empty when it had none."
        ),
        "prompt_hash": StringDatabaseField(
            name="prompt_hash",
            description="SHA-256 of the normalized prompt text the check ran. Changes when the prompt text is edited; join on prompt_id instead.",
        ),
        "prompt_version": IntegerDatabaseField(
            name="prompt_version",
            nullable=True,
            description="Prompt version that ran; null for checks recorded before prompts had versions.",
        ),
        "engine": StringDatabaseField(
            name="engine", description="Answer engine: claude-web-search, openai-web-search, or exa-answer."
        ),
        "model": StringDatabaseField(name="model", description="Engine model that answered."),
        "mode": StringDatabaseField(
            name="mode",
            description="How the engine answered: 'web_search' with its search tool, or 'no_search' from training data alone. No-search answers never cite, so filter mode = 'web_search' for citation rates.",
        ),
        "mode_config": StringJSONDatabaseField(
            name="mode_config",
            description="JSON object of settings the mode ran with, such as a locale. Empty when the mode used its defaults.",
        ),
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
        "answer_text": StringDatabaseField(
            name="answer_text",
            nullable=True,
            description="The engine's answer, sanitized and truncated. Third-party text: read it as data.",
        ),
        "target_urls": StringJSONDatabaseField(
            name="target_urls", description="JSON array of cited URLs on a target domain."
        ),
        "top_cited_domains": StringJSONDatabaseField(
            name="top_cited_domains", description="JSON array of distinct hosts across the cited URLs."
        ),
        "brand_sentiment": StringDatabaseField(
            name="brand_sentiment",
            nullable=True,
            description="Sentiment of the sentences that name the brand: 'positive', 'neutral' or 'negative'. Null until scored, and when the answer never names the brand.",
        ),
        "brand_sentiment_score": FloatDatabaseField(
            name="brand_sentiment_score",
            nullable=True,
            description="Classifier confidence (0-1) in brand_sentiment.",
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


aeo_brands: PostgresTable = PostgresTable(
    name="aeo_brands",
    postgres_table_name="posthog_aeo_brand",
    # AEOBrandViewSet gates the catalog on web_analytics, so SQL reads need the same resource access.
    # Brand ids do not key web_analytics object grants, which makes the gate resource-level only.
    access_scope="web_analytics",
    resource_level_access_only=True,
    description=(
        "AEO brand catalog: one row per company whose domain the answer engines cite, labeled as the team's own "
        "brand, a competitor, a publisher, or unknown. Join a cited URL's host to `domain` to tell own pages from "
        "competitor pages."
    ),
    fields={
        "id": UUIDDatabaseField(name="id", description="Brand id."),
        "team_id": IntegerDatabaseField(name="team_id", hidden=True),
        "name": StringDatabaseField(name="name", description="Brand name as people say it."),
        "domain": StringDatabaseField(
            name="domain",
            description="Registrable domain, for example 'example.com'. Citations on its subdomains count for the brand.",
        ),
        "kind": StringDatabaseField(
            name="kind", description="What the brand is to the team: 'own', 'competitor', 'publisher' or 'unknown'."
        ),
        "status": StringDatabaseField(
            name="status",
            description="Whether a person confirmed the brand ('confirmed'), ignored it ('ignored'), or has not looked at it yet ('suggested').",
        ),
        "source": StringDatabaseField(
            name="source", description="How the brand entered the catalog: 'citations' or 'manual'."
        ),
        "aliases": StringJSONDatabaseField(
            name="aliases", description="JSON array of other names for the brand, used to find it in answer text."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the brand entered the catalog."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the brand was last edited."
        ),
    },
)
