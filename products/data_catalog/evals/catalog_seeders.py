"""Seeder hooks that install the semantic layer catalog from ``catalog_synthesizer`` into a per-case team.

The seeder contract takes no per-case parameters, so each case state has its own function. Every seeder
returns the names its scorers grade against.
"""

from __future__ import annotations

from collections.abc import Iterable
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
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    ACCOUNTS_COLUMNS,
    ACCOUNTS_DECOY_ROWS,
    ACCOUNTS_DECOY_TABLE,
    ACCOUNTS_ROWS,
    ACCOUNTS_TABLE,
    ACTIVATION_FUNNEL_METRIC,
    AMOUNT_COLUMNS,
    CHURN_RISK_INJECTED_METRIC,
    CHURN_RISK_METRIC,
    CHURN_RISK_MISSING_SOURCE_METRIC,
    DEALS_ACCOUNT_RELATIONSHIP_FIELD,
    DEALS_ACCOUNT_RELATIONSHIP_REASONING,
    DEALS_COLUMNS,
    DEALS_LEGACY_ROWS,
    DEALS_LEGACY_TABLE,
    DEALS_LEGACY_TABLE_DESCRIPTION,
    DEALS_ROWS,
    DEALS_TABLE,
    DEALS_TABLE_DESCRIPTION,
    DEALS_V3_TABLE,
    DEALS_V3_TABLE_DESCRIPTION,
    LOCAL_AMOUNT_DESCRIPTION,
    LOCAL_AMOUNT_ROWS,
    LOCAL_AMOUNT_TABLE,
    MRR_METRIC,
    NOISE_METRICS,
    PAYING_CUSTOMERS_METRIC,
    USD_AMOUNT_DESCRIPTION,
    USD_AMOUNT_ROWS,
    USD_AMOUNT_TABLE,
    WAREHOUSE_SIGNUPS_METRIC,
    CatalogMetric,
)
from products.data_catalog.evals.seeders import _FLOAT_COLUMN, _INTEGER_COLUMN, _STRING_COLUMN, _synced_table
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import (
    ExternalDataSourceType,
    WarehouseColumnAnnotationDescriptionSource,
)

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

_DEALS_COLUMN_TYPES = {
    "deal_id": _INTEGER_COLUMN,
    "account_id": _INTEGER_COLUMN,
    "stage": _STRING_COLUMN,
    "amount_usd": _FLOAT_COLUMN,
}
_AMOUNT_COLUMN_TYPES = {"deal_id": _INTEGER_COLUMN, "currency": _STRING_COLUMN, "amount": _FLOAT_COLUMN}
_ACCOUNTS_COLUMN_TYPES = {"account_id": _INTEGER_COLUMN, "industry": _STRING_COLUMN}
# The Hedgebox demo data ships this table; a node metric over it needs it to be queryable in the case team.
_WAREHOUSE_SIGNUPS_CHECK = "SELECT count() FROM signups"

assert tuple(_DEALS_COLUMN_TYPES) == DEALS_COLUMNS
assert tuple(_AMOUNT_COLUMN_TYPES) == AMOUNT_COLUMNS
assert tuple(_ACCOUNTS_COLUMN_TYPES) == ACCOUNTS_COLUMNS


def _team_and_user(context: CustomPromptSandboxContext) -> tuple[Team, User]:
    return Team.objects.get(pk=context.team_id), User.objects.get(pk=context.user_id)


def _install(context: CustomPromptSandboxContext, metrics: Iterable[CatalogMetric]) -> list[dict[str, str]]:
    team, user = _team_and_user(context)
    installed = []
    for spec in metrics:
        metric = upsert_metric(
            team=team,
            user=user,
            name=spec.name,
            display_name=spec.display_name,
            description=spec.description,
            unit=spec.unit,
            definition=spec.definition,
            overwrite=True,
        )
        approve_metric(metric, user)
        installed.append({"name": spec.name, "status": "approved"})
    return installed


def _catalog(context: CustomPromptSandboxContext, *needles: CatalogMetric) -> dict[str, Any]:
    installed = _install(context, (*NOISE_METRICS, *needles))
    return {"catalog": {"size": len(installed), "needles": [needle.name for needle in needles]}}


def seed_noise_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _catalog(context)


def seed_catalog_with_mrr(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _catalog(context, MRR_METRIC)


def seed_catalog_with_account_engagement(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _catalog(context, ACCOUNT_ENGAGEMENT_METRIC)


def seed_catalog_for_board_update(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return _catalog(context, MRR_METRIC, PAYING_CUSTOMERS_METRIC, ACCOUNT_ENGAGEMENT_METRIC)


def seed_mrr_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [MRR_METRIC])}


def seed_pricing_metrics(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [MRR_METRIC, PAYING_CUSTOMERS_METRIC])}


def seed_account_engagement_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [ACCOUNT_ENGAGEMENT_METRIC])}


def seed_activation_funnel_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [ACTIVATION_FUNNEL_METRIC])}


def seed_churn_risk_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [CHURN_RISK_METRIC])}


def seed_churn_risk_missing_source_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [CHURN_RISK_MISSING_SOURCE_METRIC])}


def seed_churn_risk_injected_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {"metrics": _install(context, [CHURN_RISK_INJECTED_METRIC])}


def seed_warehouse_signups_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    # A table the case cannot read would score the agent 0 for an infrastructure fault, so fail the seed instead.
    response = execute_hogql_query(_WAREHOUSE_SIGNUPS_CHECK, team=team, user=user)
    if getattr(response, "error", None) or not response.results:
        raise RuntimeError("The warehouse signups metric needs the Hedgebox `signups` warehouse table.")
    return {"metrics": _install(context, [WAREHOUSE_SIGNUPS_METRIC])}


def _deals_table(
    team: Team, user: User, *, name: str, description: str, rows: tuple[tuple[Any, ...], ...]
) -> DataWarehouseTable:
    synced = _synced_table(
        team,
        user,
        source_type=ExternalDataSourceType.POSTGRES,
        schema_name=name,
        table_name=name,
        columns=_DEALS_COLUMN_TYPES,
        rows=rows,
        descriptions={"": description},
        description_source=WarehouseColumnAnnotationDescriptionSource.USER_EDITED,
    )
    # information_schema.tables reports row_count from the table row, which a real sync fills in.
    DataWarehouseTable.objects.filter(pk=synced.table_id).update(row_count=len(rows))
    return DataWarehouseTable.objects.get(pk=synced.table_id)


def seed_deal_tables(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    current = _deals_table(team, user, name=DEALS_TABLE, description=DEALS_TABLE_DESCRIPTION, rows=DEALS_ROWS)
    legacy = _deals_table(
        team, user, name=DEALS_LEGACY_TABLE, description=DEALS_LEGACY_TABLE_DESCRIPTION, rows=DEALS_LEGACY_ROWS
    )
    _deals_table(team, user, name=DEALS_V3_TABLE, description=DEALS_V3_TABLE_DESCRIPTION, rows=())
    certify(propose_certification(team=team, user=user, table_id=str(current.id)), user)
    deprecate(propose_certification(team=team, user=user, table_id=str(legacy.id)), user)
    return {"deal_tables": {"certified": DEALS_TABLE, "deprecated": DEALS_LEGACY_TABLE, "empty": DEALS_V3_TABLE}}


def seed_amount_currency_tables(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    for name, rows, description in (
        (USD_AMOUNT_TABLE, USD_AMOUNT_ROWS, USD_AMOUNT_DESCRIPTION),
        (LOCAL_AMOUNT_TABLE, LOCAL_AMOUNT_ROWS, LOCAL_AMOUNT_DESCRIPTION),
    ):
        _synced_table(
            team,
            user,
            source_type=ExternalDataSourceType.POSTGRES,
            schema_name=name,
            table_name=name,
            columns=_AMOUNT_COLUMN_TYPES,
            rows=rows,
            descriptions={"amount": description},
            description_source=WarehouseColumnAnnotationDescriptionSource.USER_EDITED,
        )
    return {"amount_tables": {"usd": USD_AMOUNT_TABLE, "local": LOCAL_AMOUNT_TABLE}}


def seed_deal_account_relationship(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    _deals_table(team, user, name=DEALS_TABLE, description=DEALS_TABLE_DESCRIPTION, rows=DEALS_ROWS)
    for name, rows in ((ACCOUNTS_TABLE, ACCOUNTS_ROWS), (ACCOUNTS_DECOY_TABLE, ACCOUNTS_DECOY_ROWS)):
        _synced_table(
            team,
            user,
            source_type=ExternalDataSourceType.POSTGRES,
            schema_name=name,
            table_name=name,
            columns=_ACCOUNTS_COLUMN_TYPES,
            rows=rows,
            descriptions={},
        )
    DataWarehouseJoin.objects.create(
        team=team,
        source_table_name=DEALS_TABLE,
        source_table_key="account_id",
        joining_table_name=ACCOUNTS_DECOY_TABLE,
        joining_table_key="account_id",
        field_name="account_import",
    )
    proposal = propose_relationship(
        team=team,
        user=user,
        source_table_name=DEALS_TABLE,
        source_table_key="account_id",
        joining_table_name=ACCOUNTS_TABLE,
        joining_table_key="account_id",
        field_name=DEALS_ACCOUNT_RELATIONSHIP_FIELD,
        confidence=0.97,
        reasoning=DEALS_ACCOUNT_RELATIONSHIP_REASONING,
    )
    # Acceptance validates the join with a live query; the seeded tables are already proven readable above.
    with patch("products.data_catalog.backend.logic.relationships.execute_hogql_query"):
        accept_proposal(proposal, user)
    return {"relationship": {"source": DEALS_TABLE, "target": ACCOUNTS_TABLE, "decoy": ACCOUNTS_DECOY_TABLE}}
