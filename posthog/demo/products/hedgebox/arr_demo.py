"""ARR demo: Salesforce + Postgres warehouse tables, a dbt-style modeling
chain, and a "Revenue over time" insight on top.

Mirrors the existing `_set_up_demo_data_warehouse_tables` flow in
`HedgeboxMatrix` (CSV → MinIO → DataWarehouseTable). On top of the tables this
module adds:

  - 4 DataWarehouseSavedQuery rows that form the modeling chain
    (stg_billing_* → prod_postgres_invoice_with_annual)
  - 1 Insight named "Revenue over time" that runs the ARR + SF-forecast query

The catalog agent is expected to derive a CatalogMetric from the insight (or
the underlying SQL) in a separate pass — this module deliberately stops at
the insight.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from posthog.models.insight import Insight
from posthog.models.team.team import Team
from posthog.models.user import User

from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.models.util import CLICKHOUSE_HOGQL_MAPPING, clean_type
from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix

# Deterministic seed so re-runs produce the same data.
ARR_DEMO_RANDOM_SEED = 42

POSTGRES_PREFIX = "prod_postgres_"
SALESFORCE_PREFIX = "salesforce_"

INSIGHT_NAME = "Revenue over time"
INSIGHT_DESCRIPTION = (
    "Monthly ARR (×12) plus probability-weighted Salesforce pipeline for the next two months. "
    "Applies a 4% expected-churn discount to forecasted (upcoming) invoices."
)


# ----------------------------------------------------------------------------
# Synthetic data generation
# ----------------------------------------------------------------------------


def _month_floor(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _generate_customers(n: int = 30) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for i in range(1, n + 1):
        plan_starts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=30 * (i % 6))
        rows.append(
            (
                10_000 + i,
                f"org_{i:04d}",
                f"DemoCo {i}",
                1 if i % 3 == 0 else 2,
                plan_starts.timestamp() if i % 2 == 0 else None,
                (plan_starts + timedelta(days=365)).timestamp() if i % 2 == 0 else None,
                10.0 if i % 4 == 0 else None,
                "true" if i % 5 == 0 else None,
            )
        )
    return rows


CUSTOMER_COLUMNS: dict[str, str] = {
    "id": "Int64",
    "organization_id": "String",
    "name": "String",
    "license_id": "Int64",
    "meta_annual_plan_starts_at": "Nullable(Float64)",
    "meta_annual_plan_ends_at": "Nullable(Float64)",
    "meta_credit_discount_percent": "Nullable(Float64)",
    "meta_usage_based_mrr": "Nullable(String)",
}


def _generate_invoices(customer_ids: list[int], now: datetime, months_back: int = 6) -> list[tuple[Any, ...]]:
    rng = random.Random(ARR_DEMO_RANDOM_SEED)
    anchor = _month_floor(now) - timedelta(days=30 * months_back)
    rows: list[tuple[Any, ...]] = []
    seq = 0
    for offset in range(months_back):
        period_start = anchor + timedelta(days=30 * offset)
        period_end = period_start + timedelta(days=30)
        for customer_id in customer_ids:
            if rng.random() < 0.2:
                continue
            seq += 1
            mrr = round(rng.choice([500, 1200, 2400, 5000, 12000, 25000]) * (0.8 + rng.random() * 0.6), 2)
            status = rng.choices(["paid", "open", "void"], weights=[85, 10, 5])[0]
            data_blob = {
                "id": f"in_demo_{seq:05d}",
                "paid": status == "paid",
                "status": status,
                "charge": {"amount_refunded": rng.choice([0, 0, 0, 5000, 15000]) if status == "paid" else 0},
                "metadata": {},
            }
            rows.append(
                (
                    f"in_demo_{seq:05d}",
                    customer_id,
                    period_start.isoformat(),
                    period_end.isoformat(),
                    mrr,
                    status,
                    json.dumps(data_blob),
                    None,
                )
            )
    return rows


INVOICE_COLUMNS: dict[str, str] = {
    "id": "String",
    "customer_id": "Int64",
    "period_start": "String",
    "period_end": "String",
    "mrr": "Float64",
    "data_status": "String",
    "data": "String",
    "data_amortize_until": "Nullable(String)",
}


def _generate_upcoming_invoices(
    customer_ids: list[int], now: datetime, months_forward: int = 2
) -> list[tuple[Any, ...]]:
    rng = random.Random(ARR_DEMO_RANDOM_SEED + 1)
    next_month_start = _month_floor(_month_floor(now) + timedelta(days=31))
    rows: list[tuple[Any, ...]] = []
    seq = 0
    for offset in range(months_forward):
        period_start = next_month_start + timedelta(days=30 * offset)
        period_end = period_start + timedelta(days=30)
        for customer_id in customer_ids:
            if rng.random() < 0.3:
                continue
            seq += 1
            forecasted_mrr = round(rng.choice([500, 1200, 2400, 5000, 12000, 25000]) * (0.8 + rng.random() * 0.6), 2)
            rows.append(
                (
                    f"upinv_demo_{seq:05d}",
                    customer_id,
                    period_start.isoformat(),
                    period_end.isoformat(),
                    forecasted_mrr,
                    json.dumps({"platform": forecasted_mrr * 0.7, "addons": forecasted_mrr * 0.3}),
                )
            )
    return rows


UPCOMING_COLUMNS: dict[str, str] = {
    "id": "String",
    "customer_id": "Int64",
    "period_start": "String",
    "period_end": "String",
    "forecasted_mrr": "Float64",
    "mrr_per_product": "String",
}


def _generate_salesforce_opportunities(now: datetime, n: int = 50) -> list[tuple[Any, ...]]:
    rng = random.Random(ARR_DEMO_RANDOM_SEED + 2)
    annual_record_type = "012Hp000001eARsIAM"
    rows: list[tuple[Any, ...]] = []
    for i in range(1, n + 1):
        close_date = _month_floor(now) + timedelta(days=rng.randint(-30, 90))
        amount = round(rng.choice([10_000, 25_000, 60_000, 120_000, 250_000]) * (0.8 + rng.random() * 0.6), 2)
        is_closed = rng.random() < 0.2
        probability = 100 if is_closed else rng.choice([20, 40, 60, 80])
        rows.append(
            (
                f"006Hp{i:09d}",
                f"Opportunity {i} - DemoCo",
                close_date.isoformat(),
                amount,
                amount * 0.95,
                probability,
                is_closed,
                rng.choice(["Annual Contract", "Monthly Contract", "Renewal"]),
                annual_record_type,
                False,
                False,
                rng.choice(["Prospecting", "Qualification", "Proposal", "Negotiation", "Closed Won"]),
            )
        )
    return rows


OPPORTUNITY_COLUMNS: dict[str, str] = {
    "id": "String",
    "name": "String",
    "close_date": "String",
    "amount": "Float64",
    "amount_discounted_c": "Float64",
    "probability": "Int64",
    "is_closed": "Bool",
    "type": "String",
    "record_type_id": "String",
    "self_serve_no_interaction_c": "Bool",
    "self_serve_post_engagement_c": "Bool",
    "stage_name": "String",
}


# ----------------------------------------------------------------------------
# Saved-query bodies — simplified vs the dbt originals but keep the shape
# ----------------------------------------------------------------------------


STG_BILLING_INVOICE_EXTRACTED = """
SELECT
    id,
    customer_id,
    period_start,
    period_end,
    mrr,
    data_status,
    data,
    JSONExtractString(data, 'id') AS data_id,
    JSONExtractInt(data, 'charge', 'amount_refunded') AS data_charge_amount_refunded
FROM prod_postgres_billing_invoice
WHERE data_status NOT IN ('void', 'uncollectible')
""".strip()

STG_BILLING_UPCOMING_INVOICE = """
SELECT
    id,
    customer_id,
    period_start,
    period_end,
    forecasted_mrr,
    mrr_per_product
FROM prod_postgres_billing_upcominginvoice
""".strip()

STG_BILLING_CUSTOMER_EXTRACTED = """
SELECT
    id,
    organization_id,
    name,
    license_id,
    meta_annual_plan_starts_at,
    meta_annual_plan_ends_at,
    meta_credit_discount_percent,
    meta_usage_based_mrr
FROM prod_postgres_billing_customer
WHERE license_id IN (1, 2)
""".strip()

# Simplified union view: completed paid invoices + forecasted upcoming. Keeps
# the same shape (type / period_end / mrr / customer_id / data) that the ARR
# query consumes, with the credit_discount_percent calculation collapsed away.
PROD_POSTGRES_INVOICE_WITH_ANNUAL = """
SELECT
    'completed' AS type,
    toDateTime(period_start, 'UTC') AS period_start,
    toDateTime(period_end, 'UTC') AS period_end,
    data,
    toFloat(mrr) AS mrr,
    customer_id,
    c.organization_id AS organization_id
FROM stg_billing_invoice_extracted AS i
LEFT JOIN stg_billing_customer_extracted AS c ON c.id = i.customer_id
WHERE JSONExtractString(i.data, 'status') NOT IN ('void', 'uncollectible')

UNION ALL

SELECT
    'upcoming' AS type,
    toDateTime(period_start, 'UTC') AS period_start,
    toDateTime(period_end, 'UTC') AS period_end,
    '{}' AS data,
    toFloat(forecasted_mrr) AS mrr,
    u.customer_id,
    c.organization_id AS organization_id
FROM stg_billing_upcoming_invoice AS u
LEFT JOIN stg_billing_customer_extracted AS c ON c.id = u.customer_id
""".strip()

# Final ARR rollup with a probability-weighted Salesforce pipeline boost.
# Preserves the original query's monthly granularity and the 4% expected-churn
# discount on upcoming invoices.
ARR_WITH_SF_FORECAST_QUERY = """
WITH revenue AS (
    SELECT
        dateTrunc('month', period_end) AS period,
        round(sum(if(type = 'upcoming', toFloat(mrr) * 0.96, toFloat(mrr)))) AS MRR_nr,
        round(sum(if(type = 'upcoming', toFloat(mrr) * 0.96, toFloat(mrr))) * 12) AS ARR_nr
    FROM prod_postgres_invoice_with_annual
    WHERE period_end < dateTrunc('month', now()) + toIntervalMonth(2)
    GROUP BY period
),
projected_deals AS (
    SELECT
        dateTrunc('month', toDateTime(close_date, 'UTC')) AS projected_period,
        sum(toFloat(amount_discounted_c) * toFloat(probability) / 100) AS weighted_projected_amount
    FROM salesforce_opportunity
    WHERE is_closed = false
        AND type != 'Monthly Contract'
        AND self_serve_no_interaction_c = false
        AND self_serve_post_engagement_c = false
        AND dateTrunc('month', toDateTime(close_date, 'UTC')) < dateTrunc('month', now()) + toIntervalMonth(2)
    GROUP BY projected_period
)
SELECT
    r.period,
    r.ARR_nr,
    r.ARR_nr + coalesce(p.weighted_projected_amount, 0) AS ARR_with_sf_forecast
FROM revenue AS r
LEFT JOIN projected_deals AS p ON r.period = p.projected_period
ORDER BY r.period
""".strip()


# ----------------------------------------------------------------------------
# Upsert helpers — adapted from Georgiy's load_warehouse_orm.py to dodge the
# `SELECT FOR UPDATE` over nullable-FK join that breaks `update_or_create` on
# DataWarehouseTable.
# ----------------------------------------------------------------------------


def _upsert(manager: Any, *, lookup: dict[str, Any], defaults: dict[str, Any]) -> Any:
    try:
        obj = manager.get(**lookup)
        for field, value in defaults.items():
            setattr(obj, field, value)
        obj.save()
        return obj
    except manager.model.DoesNotExist:
        return manager.create(**lookup, **defaults)


def _upsert_source(*, team: Team, name: str, source_type: str, prefix: str) -> ExternalDataSource:
    return _upsert(
        ExternalDataSource.objects,
        lookup={"team": team, "prefix": prefix, "source_type": source_type},
        defaults={
            "source_id": f"demo_{name}",
            "connection_id": "",
            "status": ExternalDataSource.Status.COMPLETED,
            "description": f"Demo {name} source seeded by generate_demo_data",
            "created_via": "generate_demo_data",
            "are_tables_created": True,
            "job_inputs": {},
        },
    )


def _saved_query_columns_payload(types: dict[str, str]) -> dict[str, dict[str, str | bool]]:
    """Build the `columns` JSON DataWarehouseSavedQuery uses to advertise its output
    schema to the HogQL resolver. Without this, references like `id` in a downstream
    query fail to resolve.
    """
    out: dict[str, dict[str, str | bool]] = {}
    for col, ch_type in types.items():
        base = clean_type(ch_type)
        out[col] = {
            "hogql": CLICKHOUSE_HOGQL_MAPPING[base].__name__,
            "clickhouse": ch_type,
            "valid": True,
        }
    return out


def _upsert_saved_query(*, team: Team, name: str, query: str, columns: dict[str, str]) -> DataWarehouseSavedQuery:
    return _upsert(
        DataWarehouseSavedQuery.objects,
        lookup={"team": team, "name": name},
        defaults={
            "query": {"kind": "HogQLQuery", "query": query},
            "columns": _saved_query_columns_payload(columns),
            "status": DataWarehouseSavedQuery.Status.COMPLETED,
            "latest_error": None,
            "is_materialized": False,
            "deleted": False,
        },
    )


def _upsert_insight(*, team: Team, name: str, description: str, hogql: str) -> Insight:
    """Mirror what 'Save as Insight' does in the SQL editor: wrap the HogQL in a
    DataVisualizationNode so the result is renderable as a chart.
    """
    return _upsert(
        Insight.objects,
        lookup={"team": team, "name": name},
        defaults={
            "description": description,
            "query": {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": hogql},
            },
            "saved": True,
            "deleted": False,
            "filters": {},
        },
    )


# ----------------------------------------------------------------------------
# Entry point — called from HedgeboxMatrix._set_up_demo_data_warehouse_tables
# ----------------------------------------------------------------------------


def seed_arr_demo(matrix: HedgeboxMatrix, team: Team, user: User, credential: DataWarehouseCredential) -> None:
    """Create the ARR demo surface for `team`.

    Reuses the matrix's existing `_upsert_demo_data_warehouse_table_contents`
    helper for CSV→MinIO writes so the storage path stays consistent with
    other demo tables (paid_bills, signups, uploaded_files).

    Adds on top: Postgres + Salesforce ExternalDataSource rows, a saved-query
    modeling chain, and a "Revenue over time" insight. Idempotent on
    (team, name) — re-running replaces prior demo rows.
    """
    now = matrix.now

    # 1. Synthetic data
    customers = _generate_customers()
    customer_ids = [int(row[0]) for row in customers]
    invoices = _generate_invoices(customer_ids, now=now)
    upcoming = _generate_upcoming_invoices(customer_ids, now=now)
    opportunities = _generate_salesforce_opportunities(now=now)

    # 2. Earlier seeder versions may have left rows behind; clean up so the
    #    saved-query names below don't collide with stale warehouse tables.
    DataWarehouseTable.raw_objects.filter(
        team=team,
        name__in=(
            "stg_billing_invoice_extracted",
            "stg_billing_upcoming_invoice",
            "stg_billing_customer_extracted",
            "prod_postgres_invoice_with_annual",
        ),
        deleted=False,
    ).update(deleted=True)

    # 3. Sources
    postgres_source = _upsert_source(
        team=team, name="postgres", source_type=ExternalDataSourceType.POSTGRES, prefix=POSTGRES_PREFIX
    )
    salesforce_source = _upsert_source(
        team=team, name="salesforce", source_type=ExternalDataSourceType.SALESFORCE, prefix=SALESFORCE_PREFIX
    )

    # 4. Warehouse tables via the existing matrix helper (CSV → MinIO → row).
    #    The helper doesn't take a source FK, so we link them after the fact.
    table_specs: list[tuple[str, dict[str, str], list[tuple[Any, ...]], ExternalDataSource]] = [
        ("prod_postgres_billing_customer", CUSTOMER_COLUMNS, customers, postgres_source),
        ("prod_postgres_billing_invoice", INVOICE_COLUMNS, invoices, postgres_source),
        ("prod_postgres_billing_upcominginvoice", UPCOMING_COLUMNS, upcoming, postgres_source),
        ("salesforce_opportunity", OPPORTUNITY_COLUMNS, opportunities, salesforce_source),
    ]
    for table_name, columns, rows, source in table_specs:
        matrix._upsert_demo_data_warehouse_table_contents(
            team=team,
            user=user,
            credential=credential,
            table_name=table_name,
            columns=columns,
            rows=rows,
        )
        # Link the table back to its source so the catalog UI can attribute it.
        DataWarehouseTable.raw_objects.filter(team=team, name=table_name).update(external_data_source=source)

    # 5. Saved-query modeling chain. Explicit `columns` payloads so HogQL can
    #    resolve downstream field references without materializing each query.
    _upsert_saved_query(
        team=team,
        name="stg_billing_invoice_extracted",
        query=STG_BILLING_INVOICE_EXTRACTED,
        columns={
            "id": "String",
            "customer_id": "Int64",
            "period_start": "String",
            "period_end": "String",
            "mrr": "Float64",
            "data_status": "String",
            "data": "String",
            "data_id": "Nullable(String)",
            "data_charge_amount_refunded": "Nullable(Int64)",
        },
    )
    _upsert_saved_query(
        team=team,
        name="stg_billing_upcoming_invoice",
        query=STG_BILLING_UPCOMING_INVOICE,
        columns={
            "id": "String",
            "customer_id": "Int64",
            "period_start": "String",
            "period_end": "String",
            "forecasted_mrr": "Float64",
            "mrr_per_product": "String",
        },
    )
    _upsert_saved_query(
        team=team,
        name="stg_billing_customer_extracted",
        query=STG_BILLING_CUSTOMER_EXTRACTED,
        columns={
            "id": "Int64",
            "organization_id": "String",
            "name": "String",
            "license_id": "Int64",
            "meta_annual_plan_starts_at": "Nullable(Float64)",
            "meta_annual_plan_ends_at": "Nullable(Float64)",
            "meta_credit_discount_percent": "Nullable(Float64)",
            "meta_usage_based_mrr": "Nullable(String)",
        },
    )
    _upsert_saved_query(
        team=team,
        name="prod_postgres_invoice_with_annual",
        query=PROD_POSTGRES_INVOICE_WITH_ANNUAL,
        columns={
            "type": "String",
            "period_start": "DateTime",
            "period_end": "DateTime",
            "data": "String",
            "mrr": "Float64",
            "customer_id": "Int64",
            "organization_id": "Nullable(String)",
        },
    )

    # 6. Renderable insight on top.
    _upsert_insight(
        team=team,
        name=INSIGHT_NAME,
        description=INSIGHT_DESCRIPTION,
        hogql=ARR_WITH_SF_FORECAST_QUERY,
    )
