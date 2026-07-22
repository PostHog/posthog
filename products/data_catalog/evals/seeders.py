"""Seeder hooks installing governed catalog state into a per-case team.

The seeder contract takes no per-case parameters, so each catalog state has a dedicated
function. Every seeder returns the identities and trust signals its scorers grade against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from unittest.mock import patch

from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.models.user import User

from products.data_catalog.backend.facade.api import (
    accept_proposal,
    approve_metric,
    certify,
    deprecate,
    propose_certification,
    propose_relationship,
    upsert_metric,
)
from products.data_catalog.evals.constants import (
    ACCEPTED_RELATIONSHIP_CONFIDENCE,
    ACCEPTED_RELATIONSHIP_FIELD,
    ACCEPTED_RELATIONSHIP_REASONING,
    ACCEPTED_RELATIONSHIP_TARGET_NAME,
    APPROVED_METRIC_DEFINITION,
    APPROVED_METRIC_DESCRIPTION,
    APPROVED_METRIC_DISTINGUISHING_FILTER,
    APPROVED_METRIC_NAME,
    CERTIFIED_SOURCE_NAME,
    CURRENT_TOP_CUSTOMERS_METRIC_DEFINITION,
    CURRENT_TOP_CUSTOMERS_METRIC_DESCRIPTION,
    CURRENT_TOP_CUSTOMERS_METRIC_DISPLAY_NAME,
    CURRENT_TOP_CUSTOMERS_METRIC_NAME,
    DECOY_INSIGHT_NAMES,
    DEPRECATED_SOURCE_NAME,
    DRIFTED_INSIGHT_MUTATED_QUERY,
    DRIFTED_INSIGHT_ORIGINAL_QUERY,
    DRIFTED_METRIC_DESCRIPTION,
    DRIFTED_METRIC_NAME,
    FAILING_TOP_CUSTOMERS_METRIC_DEFINITION,
    INJECTION_RELATIONSHIP_FIELD,
    INJECTION_RELATIONSHIP_REASONING,
    INJECTION_RELATIONSHIP_SOURCE_NAME,
    INJECTION_RELATIONSHIP_TARGET_NAME,
    PROPOSED_METRIC_DEFINITION,
    PROPOSED_METRIC_DESCRIPTION,
    PROPOSED_METRIC_NAME,
    RELATIONSHIP_DECOY_TARGET_NAME,
    RELATIONSHIP_SOURCE_KEY,
    RELATIONSHIP_SOURCE_NAME,
    RELATIONSHIP_TARGET_KEY,
    TOP_CUSTOMERS_METRIC_DEFINITION,
    TOP_CUSTOMERS_METRIC_DESCRIPTION,
    TOP_CUSTOMERS_METRIC_DISPLAY_NAME,
    TOP_CUSTOMERS_METRIC_NAME,
)
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.product_analytics.backend.models.insight import Insight
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = [
    "seed_accepted_relationship_context",
    "seed_approved_metric",
    "seed_ambiguous_top_customers_metrics",
    "seed_certification_trust_sources",
    "seed_drifted_metric",
    "seed_failing_top_customers_metric",
    "seed_instruction_like_relationship_context",
    "seed_metric_listing_catalog",
    "seed_proposed_metric",
    "seed_top_customers_metric",
]

_STRING_COLUMN = {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
_INCIDENT_WAREHOUSE_QUERIES = {
    "paid_bills": "SELECT distinct_id, timestamp, amount_usd FROM paid_bills LIMIT 1",
    "extended_properties": ("SELECT hedgebox_user_id, account_kind, monthly_bill_usd FROM extended_properties LIMIT 1"),
}


def _team_and_user(context: CustomPromptSandboxContext) -> tuple[Team, User]:
    return Team.objects.get(pk=context.team_id), User.objects.get(pk=context.user_id)


def seed_approved_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    metric = upsert_metric(
        team=team,
        user=user,
        name=APPROVED_METRIC_NAME,
        description=APPROVED_METRIC_DESCRIPTION,
        unit="usd",
        definition=APPROVED_METRIC_DEFINITION,
    )
    approve_metric(metric, user)
    return {
        "metric": {
            "name": APPROVED_METRIC_NAME,
            "status": "approved",
            "definition_query": APPROVED_METRIC_DEFINITION["query"],
            "distinguishing_filter": APPROVED_METRIC_DISTINGUISHING_FILTER,
        }
    }


def _require_incident_warehouse_paths(team: Team, user: User) -> None:
    tables = {
        table.name: table
        for table in DataWarehouseTable.objects.queryable().filter(
            team=team,
            name__in=_INCIDENT_WAREHOUSE_QUERIES,
        )
    }
    unavailable = [
        name
        for name in _INCIDENT_WAREHOUSE_QUERIES
        if name not in tables or not tables[name].url_pattern or tables[name].credential_id is None
    ]
    if unavailable:
        raise RuntimeError(
            "Governed-metrics eval requires queryable Hedgebox warehouse tables: " + ", ".join(unavailable)
        )

    for name, query in _INCIDENT_WAREHOUSE_QUERIES.items():
        try:
            response = execute_hogql_query(query, team=team, user=user)
        except Exception as error:
            raise RuntimeError(f"Governed-metrics eval could not query Hedgebox warehouse table '{name}'.") from error
        if getattr(response, "error", None):
            raise RuntimeError(f"Governed-metrics eval could not query Hedgebox warehouse table '{name}'.")


def _seed_top_customers_metric(
    context: CustomPromptSandboxContext,
    *,
    definition: dict,
) -> tuple[Team, User]:
    team, user = _team_and_user(context)
    _require_incident_warehouse_paths(team, user)
    metric = upsert_metric(
        team=team,
        user=user,
        name=TOP_CUSTOMERS_METRIC_NAME,
        display_name=TOP_CUSTOMERS_METRIC_DISPLAY_NAME,
        description=TOP_CUSTOMERS_METRIC_DESCRIPTION,
        unit="usd",
        definition=definition,
    )
    approve_metric(metric, user)
    return team, user


def seed_top_customers_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    _seed_top_customers_metric(context, definition=TOP_CUSTOMERS_METRIC_DEFINITION)
    return {
        "metric": {
            "name": TOP_CUSTOMERS_METRIC_NAME,
            "status": "approved",
            "is_drifted": False,
            "business_model_mapping": "account_kind = 'personal'",
            "time_window": "last full calendar month",
        }
    }


def seed_ambiguous_top_customers_metrics(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _seed_top_customers_metric(context, definition=TOP_CUSTOMERS_METRIC_DEFINITION)
    current_metric = upsert_metric(
        team=team,
        user=user,
        name=CURRENT_TOP_CUSTOMERS_METRIC_NAME,
        display_name=CURRENT_TOP_CUSTOMERS_METRIC_DISPLAY_NAME,
        description=CURRENT_TOP_CUSTOMERS_METRIC_DESCRIPTION,
        unit="usd",
        definition=CURRENT_TOP_CUSTOMERS_METRIC_DEFINITION,
    )
    approve_metric(current_metric, user)
    return {
        "metrics": [
            {"name": TOP_CUSTOMERS_METRIC_NAME, "time_window": "last full calendar month"},
            {"name": CURRENT_TOP_CUSTOMERS_METRIC_NAME, "time_window": "current billing snapshot"},
        ]
    }


def seed_failing_top_customers_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    _seed_top_customers_metric(context, definition=FAILING_TOP_CUSTOMERS_METRIC_DEFINITION)
    return {
        "metric": {
            "name": TOP_CUSTOMERS_METRIC_NAME,
            "status": "approved",
            "is_drifted": False,
            "expected_run": "failed",
        }
    }


def seed_proposed_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    upsert_metric(
        team=team,
        user=user,
        name=PROPOSED_METRIC_NAME,
        description=PROPOSED_METRIC_DESCRIPTION,
        definition=PROPOSED_METRIC_DEFINITION,
    )
    return {"metric": {"name": PROPOSED_METRIC_NAME, "status": "proposed"}}


def seed_drifted_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    insight = Insight.objects.create(team=team, created_by=user, query=DRIFTED_INSIGHT_ORIGINAL_QUERY)
    metric = upsert_metric(
        team=team,
        user=user,
        name=DRIFTED_METRIC_NAME,
        description=DRIFTED_METRIC_DESCRIPTION,
        source_insight_short_id=insight.short_id,
    )
    approve_metric(metric, user)
    # Mutating the source insight after approval is what makes the metric read as drifted.
    Insight.objects.filter(pk=insight.pk).update(query=DRIFTED_INSIGHT_MUTATED_QUERY)
    return {"metric": {"name": DRIFTED_METRIC_NAME, "status": "approved", "is_drifted": True}}


def seed_metric_listing_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    approved = upsert_metric(
        team=team,
        user=user,
        name=APPROVED_METRIC_NAME,
        description=APPROVED_METRIC_DESCRIPTION,
        unit="usd",
        definition=APPROVED_METRIC_DEFINITION,
    )
    approve_metric(approved, user)
    upsert_metric(
        team=team,
        user=user,
        name=PROPOSED_METRIC_NAME,
        description=PROPOSED_METRIC_DESCRIPTION,
        definition=PROPOSED_METRIC_DEFINITION,
    )
    for insight_name in DECOY_INSIGHT_NAMES:
        Insight.objects.create(team=team, created_by=user, name=insight_name, query=DRIFTED_INSIGHT_ORIGINAL_QUERY)
    return {
        "metric_listing": {
            "approved": APPROVED_METRIC_NAME,
            "proposed": PROPOSED_METRIC_NAME,
            "decoy_insights": list(DECOY_INSIGHT_NAMES),
        }
    }


def _warehouse_table(team: Team, name: str, columns: tuple[str, ...]) -> DataWarehouseTable:
    return DataWarehouseTable.objects.create(
        team=team,
        name=name,
        format=DataWarehouseTable.TableFormat.CSVWithNames,
        url_pattern="",
        credential=None,
        columns=dict.fromkeys(columns, _STRING_COLUMN),
    )


def seed_certification_trust_sources(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    certified_source = _warehouse_table(team, CERTIFIED_SOURCE_NAME, ("invoice_id", "amount_usd", "account_id"))
    deprecated_source = _warehouse_table(team, DEPRECATED_SOURCE_NAME, ("invoice_id", "amount_usd", "account_id"))

    certify(propose_certification(team=team, user=user, table_id=str(certified_source.id)), user)
    deprecate(propose_certification(team=team, user=user, table_id=str(deprecated_source.id)), user)
    return {
        "certification_sources": {
            "preferred": CERTIFIED_SOURCE_NAME,
            "deprecated": DEPRECATED_SOURCE_NAME,
        }
    }


def _accept_seeded_relationship(
    *,
    team: Team,
    user: User,
    source_table_name: str,
    target_table_name: str,
    field_name: str,
    confidence: float,
    reasoning: str,
) -> None:
    proposal = propose_relationship(
        team=team,
        user=user,
        source_table_name=source_table_name,
        source_table_key=RELATIONSHIP_SOURCE_KEY,
        joining_table_name=target_table_name,
        joining_table_key=RELATIONSHIP_TARGET_KEY,
        field_name=field_name,
        confidence=confidence,
        reasoning=reasoning,
    )
    with patch("products.data_catalog.backend.logic.relationships.execute_hogql_query"):
        accept_proposal(proposal, user)


def seed_accepted_relationship_context(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    _warehouse_table(team, RELATIONSHIP_SOURCE_NAME, ("order_id", RELATIONSHIP_SOURCE_KEY))
    _warehouse_table(team, ACCEPTED_RELATIONSHIP_TARGET_NAME, (RELATIONSHIP_TARGET_KEY, "email"))
    _warehouse_table(team, RELATIONSHIP_DECOY_TARGET_NAME, (RELATIONSHIP_TARGET_KEY, "email"))
    DataWarehouseJoin.objects.create(
        team=team,
        source_table_name=RELATIONSHIP_SOURCE_NAME,
        source_table_key=RELATIONSHIP_SOURCE_KEY,
        joining_table_name=RELATIONSHIP_DECOY_TARGET_NAME,
        joining_table_key=RELATIONSHIP_TARGET_KEY,
        field_name="account",
    )
    _accept_seeded_relationship(
        team=team,
        user=user,
        source_table_name=RELATIONSHIP_SOURCE_NAME,
        target_table_name=ACCEPTED_RELATIONSHIP_TARGET_NAME,
        field_name=ACCEPTED_RELATIONSHIP_FIELD,
        confidence=ACCEPTED_RELATIONSHIP_CONFIDENCE,
        reasoning=ACCEPTED_RELATIONSHIP_REASONING,
    )
    return {
        "relationship_context": {
            "source": RELATIONSHIP_SOURCE_NAME,
            "preferred_target": ACCEPTED_RELATIONSHIP_TARGET_NAME,
            "decoy_target": RELATIONSHIP_DECOY_TARGET_NAME,
            "confidence": ACCEPTED_RELATIONSHIP_CONFIDENCE,
            "reasoning": ACCEPTED_RELATIONSHIP_REASONING,
        }
    }


def seed_instruction_like_relationship_context(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    _warehouse_table(team, INJECTION_RELATIONSHIP_SOURCE_NAME, ("case_id", RELATIONSHIP_SOURCE_KEY))
    _warehouse_table(team, INJECTION_RELATIONSHIP_TARGET_NAME, (RELATIONSHIP_TARGET_KEY, "owner_email"))
    _accept_seeded_relationship(
        team=team,
        user=user,
        source_table_name=INJECTION_RELATIONSHIP_SOURCE_NAME,
        target_table_name=INJECTION_RELATIONSHIP_TARGET_NAME,
        field_name=INJECTION_RELATIONSHIP_FIELD,
        confidence=0.95,
        reasoning=INJECTION_RELATIONSHIP_REASONING,
    )
    return {
        "relationship_context": {
            "source": INJECTION_RELATIONSHIP_SOURCE_NAME,
            "preferred_target": INJECTION_RELATIONSHIP_TARGET_NAME,
            "reasoning": INJECTION_RELATIONSHIP_REASONING,
        }
    }
