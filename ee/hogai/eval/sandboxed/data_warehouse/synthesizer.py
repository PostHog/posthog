"""Deterministic synthetic data-warehouse generator for the information_schema eval.

Produces a large, realistic catalog — hundreds of warehouse tables across several
source connectors, a handful of data-modeling views, join relationships, and five
planted "needles" — so an agent has to *navigate* the catalog via
``system.information_schema`` rather than guess or list everything.

The module is intentionally pure: no Django, no I/O. It emits frozen dataclasses
that the seeder (``seeder.py``) translates into ORM rows + an optional CSV upload.
That split keeps generation unit-testable and byte-for-byte reproducible — all
randomness flows from the seeded mimesis bundle in ``seeders/common.py``.

The needles each target a distinct discovery skill:

* **description** — a table found only by its annotation text (opaque name).
* **column_type** — the one table with a column typed ``UUID`` (rare on purpose).
* **relationship** — two tables linked by a join, surfaced in
  ``information_schema.relationships``.
* **view** — a data-modeling view ("model") among noise views.
* **retrieval** — a queryable, S3-backed table whose columns are all declared
  ``String`` but whose row content is numeric/JSON (duck typing): the answer can
  only be had by selecting and parsing a value, not by trusting the declared type.
* **relevancy** — two near-identical tables on the same topic where only the
  annotation distinguishes the live canonical table from a frozen, superseded one:
  the agent must read metadata to pick the current table, not the stale decoy.
* **chain** — a two-hop join path (orders → account xref → account owners) the
  agent can only assemble by querying ``relationships`` iteratively, one hop at a
  time, then combining the discovered tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ee.hogai.eval.sandboxed.seeders.common import DEFAULT_NAME_SEED, NameProviders, make_name_providers

__all__ = [
    "HogqlType",
    "SynthColumn",
    "SynthTable",
    "SynthView",
    "SynthJoin",
    "NeedleSpec",
    "SynthWarehouse",
    "WarehouseSchemaSynthesizer",
    "DESC_NEEDLE_TABLE",
    "DESC_NEEDLE_PHRASE",
    "TYPE_NEEDLE_TABLE",
    "TYPE_NEEDLE_COLUMN",
    "TYPE_NEEDLE_DATA_TYPE",
    "REL_NEEDLE_SOURCE",
    "REL_NEEDLE_TARGET",
    "REL_NEEDLE_KEY",
    "REL_NEEDLE_FIELD",
    "VIEW_NEEDLE_NAME",
    "RETRIEVAL_NEEDLE_TABLE",
    "RETRIEVAL_NEEDLE_ANSWER",
    "RETRIEVAL_NEEDLE_PREFIX",
    "RETRIEVAL_NEEDLE_EVENT_ID",
    "RELEVANCY_NEEDLE_CURRENT",
    "RELEVANCY_NEEDLE_STALE",
    "RELEVANCY_NEEDLE_TOPIC",
    "CHAIN_NEEDLE_HOP3",
    "CHAIN_NEEDLE_KEY",
    "CHAIN_NEEDLE_FIELD",
]


HogqlType = Literal[
    "StringDatabaseField",
    "IntegerDatabaseField",
    "FloatDatabaseField",
    "BooleanDatabaseField",
    "DateTimeDatabaseField",
    "DateDatabaseField",
    "DecimalDatabaseField",
    "StringJSONDatabaseField",
]

# The HogQL field class is what drives ``information_schema.columns.data_type``.
# Only field classes in the warehouse ``STR_TO_HOGQL_MAPPING`` resolve to a real
# type — others fall back to ``Unknown``. (Notably ``UUIDDatabaseField`` is NOT
# supported for warehouse columns, so the rare-type needle uses ``Decimal``.) The
# ClickHouse type is only the storage hint stored on the table's columns JSON.
_CLICKHOUSE_FOR_HOGQL: dict[str, str] = {
    "StringDatabaseField": "String",
    "IntegerDatabaseField": "Int64",
    "FloatDatabaseField": "Float64",
    "BooleanDatabaseField": "Bool",
    "DateTimeDatabaseField": "DateTime64(6, 'UTC')",
    "DateDatabaseField": "Date",
    "DecimalDatabaseField": "Decimal(38, 18)",
    "StringJSONDatabaseField": "JSON",
}

# Decimal is deliberately excluded from the noise pool so the column-type needle
# (the one Decimal column in the catalog) stays unique. ``_validate`` enforces it.
_NOISE_HOGQL_TYPES: tuple[HogqlType, ...] = (
    "StringDatabaseField",
    "IntegerDatabaseField",
    "FloatDatabaseField",
    "BooleanDatabaseField",
    "DateTimeDatabaseField",
    "DateDatabaseField",
    "StringJSONDatabaseField",
)


# Needle constants — referenced verbatim by eval prompts and scorers.
DESC_NEEDLE_TABLE = "pg_ext_4471"
DESC_NEEDLE_PHRASE = "canonical MRR source of truth"
TYPE_NEEDLE_TABLE = "hubspot_sync_meta"
TYPE_NEEDLE_COLUMN = "fx_rate"
TYPE_NEEDLE_DATA_TYPE = "Decimal"
REL_NEEDLE_SOURCE = "pg_orders_2023"
REL_NEEDLE_TARGET = "salesforce_acct_xref"
REL_NEEDLE_KEY = "account_ref"
REL_NEEDLE_FIELD = "account"
VIEW_NEEDLE_NAME = "mart_active_revenue_v2"
RETRIEVAL_NEEDLE_TABLE = "stripe_raw_events"
RETRIEVAL_NEEDLE_ANSWER = "HEDGE-7731"
RETRIEVAL_NEEDLE_PREFIX = "evalwh_"
RETRIEVAL_NEEDLE_EVENT_ID = "evt_target"
# Relevancy needle — two near-identical accounts-dimension tables, identical schema;
# only the annotation says which is live (canonical) vs frozen (superseded). The
# stale table's name carries no "old"/"deprecated" tell, so the agent has to read
# the description to pick the current one rather than shortcut on the name.
RELEVANCY_NEEDLE_CURRENT = "dim_accounts_snapshot"
RELEVANCY_NEEDLE_STALE = "dim_accounts_snapshot_2023"
RELEVANCY_NEEDLE_TOPIC = "accounts dimension"
# Chain needle — the second join hop past the relationship needle, so the path is
# pg_orders_2023 -> salesforce_acct_xref -> salesforce_acct_owners.
CHAIN_NEEDLE_HOP3 = "salesforce_acct_owners"
CHAIN_NEEDLE_KEY = "owner_id"
CHAIN_NEEDLE_FIELD = "owner"


@dataclass(frozen=True)
class SynthColumn:
    name: str
    hogql: HogqlType
    nullable: bool = True
    description: str | None = None  # -> WarehouseColumnAnnotation(column_name=name)

    @property
    def clickhouse_base(self) -> str:
        """The bare ClickHouse type (no ``Nullable`` wrapper) — used for CSV-backed tables."""
        return _CLICKHOUSE_FOR_HOGQL[self.hogql]

    @property
    def clickhouse(self) -> str:
        base = self.clickhouse_base
        return f"Nullable({base})" if self.nullable else base

    def to_columns_entry(self) -> tuple[str, dict[str, Any]]:
        return self.name, {"hogql": self.hogql, "clickhouse": self.clickhouse, "valid": True}


@dataclass(frozen=True)
class SynthTable:
    name: str
    domain: str
    columns: tuple[SynthColumn, ...]
    description: str | None = None  # table-level annotation (column_name="")
    queryable: bool = False  # True only for the retrieval needle (S3-backed)
    rows: tuple[tuple[Any, ...], ...] = ()  # CSV rows, only when queryable
    row_count: int | None = None  # surfaced in information_schema.tables.row_count

    def columns_json(self) -> dict[str, Any]:
        return dict(c.to_columns_entry() for c in self.columns)


@dataclass(frozen=True)
class SynthView:
    name: str  # identifier only (validate_saved_query_name)
    columns: tuple[SynthColumn, ...]
    sql: str  # goes into query={"query": sql}
    description: str | None = None

    def columns_json(self) -> dict[str, Any]:
        return dict(c.to_columns_entry() for c in self.columns)


@dataclass(frozen=True)
class SynthJoin:
    source_table: str
    source_key: str  # bare column name (a valid HogQL field chain)
    joining_table: str
    joining_key: str
    field_name: str  # the LazyJoin field name on the source table


@dataclass(frozen=True)
class NeedleSpec:
    kind: Literal["description", "column_type", "relationship", "view", "retrieval", "relevancy", "chain"]
    answer: Any  # what the scorer checks for in the final answer / result
    target_table: str | None = None
    target_view: str | None = None
    relationship: tuple[str, str] | None = None  # (source_table, joining_table)
    distinguishing_phrase: str | None = None
    queryable: bool = False
    secondary_table: str | None = None  # the stale decoy (relevancy needle)
    chain: tuple[str, ...] = ()  # ordered join path, source-first (chain needle)


@dataclass(frozen=True)
class SynthWarehouse:
    tables: tuple[SynthTable, ...]
    views: tuple[SynthView, ...]
    joins: tuple[SynthJoin, ...]
    needles: dict[str, NeedleSpec]


# Per-domain vocabulary. Each domain contributes a name prefix, a pool of entity
# nouns (real connector tables), a column pool, and a description template.
@dataclass(frozen=True)
class _Domain:
    key: str
    prefix: str
    entities: tuple[str, ...]
    column_pool: tuple[SynthColumn, ...]
    description_template: str


def _col(name: str, hogql: HogqlType, *, nullable: bool = True) -> SynthColumn:
    return SynthColumn(name=name, hogql=hogql, nullable=nullable)


_DOMAINS: tuple[_Domain, ...] = (
    _Domain(
        key="stripe",
        prefix="stripe_",
        entities=(
            "charges",
            "invoices",
            "subscriptions",
            "refunds",
            "payouts",
            "disputes",
            "balance_transactions",
            "customers",
            "products",
            "prices",
            "coupons",
            "checkout_sessions",
            "payment_intents",
            "invoice_items",
        ),
        column_pool=(
            _col("id", "StringDatabaseField"),
            _col("amount", "IntegerDatabaseField"),
            _col("currency", "StringDatabaseField"),
            _col("customer_id", "StringDatabaseField"),
            _col("created", "DateTimeDatabaseField"),
            _col("status", "StringDatabaseField"),
            _col("metadata", "StringJSONDatabaseField"),
            _col("description", "StringDatabaseField"),
            _col("livemode", "BooleanDatabaseField"),
            _col("amount_refunded", "IntegerDatabaseField"),
        ),
        description_template="Stripe {entity} synced from the Stripe billing connector.",
    ),
    _Domain(
        key="salesforce",
        prefix="salesforce_",
        entities=(
            "accounts",
            "opportunities",
            "leads",
            "contacts",
            "campaigns",
            "opportunity_history",
            "opportunity_line_items",
            "users",
            "tasks",
            "events",
            "cases",
            "products2",
        ),
        column_pool=(
            _col("Id", "StringDatabaseField"),
            _col("Name", "StringDatabaseField"),
            _col("Amount", "FloatDatabaseField"),
            _col("StageName", "StringDatabaseField"),
            _col("CloseDate", "DateDatabaseField"),
            _col("OwnerId", "StringDatabaseField"),
            _col("IsWon", "BooleanDatabaseField"),
            _col("CreatedDate", "DateTimeDatabaseField"),
            _col("Email", "StringDatabaseField"),
            _col("Industry", "StringDatabaseField"),
        ),
        description_template="Salesforce {entity} replicated from the Salesforce CRM connector.",
    ),
    _Domain(
        key="hubspot",
        prefix="hubspot_",
        entities=(
            "deals",
            "companies",
            "contacts",
            "emails",
            "tickets",
            "deal_pipelines",
            "deal_stage_history",
            "engagements",
            "owners",
            "line_items",
            "forms",
            "calls",
        ),
        column_pool=(
            _col("hs_object_id", "StringDatabaseField"),
            _col("dealstage", "StringDatabaseField"),
            _col("amount", "FloatDatabaseField"),
            _col("closedate", "DateTimeDatabaseField"),
            _col("hs_lastmodifieddate", "DateTimeDatabaseField"),
            _col("pipeline", "StringDatabaseField"),
            _col("dealname", "StringDatabaseField"),
            _col("is_closed", "BooleanDatabaseField"),
            _col("num_contacted_notes", "IntegerDatabaseField"),
            _col("properties", "StringJSONDatabaseField"),
        ),
        description_template="HubSpot {entity} synced from the HubSpot marketing connector.",
    ),
    _Domain(
        key="postgres_replica",
        prefix="pg_",
        entities=(
            "users",
            "orders",
            "order_items",
            "products",
            "payments",
            "sessions",
            "audit_log",
            "addresses",
            "carts",
            "shipments",
            "reviews",
            "inventory",
            "refund_requests",
        ),
        column_pool=(
            _col("id", "IntegerDatabaseField", nullable=False),
            _col("email", "StringDatabaseField"),
            _col("created_at", "DateTimeDatabaseField"),
            _col("updated_at", "DateTimeDatabaseField"),
            _col("total_cents", "IntegerDatabaseField"),
            _col("is_active", "BooleanDatabaseField"),
            _col("payload", "StringJSONDatabaseField"),
            _col("status", "StringDatabaseField"),
            _col("quantity", "IntegerDatabaseField"),
            _col("price", "FloatDatabaseField"),
        ),
        description_template="Postgres {entity} streamed from the production read replica.",
    ),
    _Domain(
        key="analytics",
        prefix="model_",
        entities=(
            "stg_stripe_charges",
            "stg_hubspot_deals",
            "fct_subscriptions",
            "fct_orders",
            "dim_customers",
            "dim_products",
            "mart_revenue_daily",
            "mart_funnel_weekly",
            "int_active_accounts",
            "int_billing_events",
        ),
        column_pool=(
            _col("date_day", "DateDatabaseField"),
            _col("revenue", "FloatDatabaseField"),
            _col("active_subscriptions", "IntegerDatabaseField"),
            _col("active_customers", "IntegerDatabaseField"),
            _col("mrr", "FloatDatabaseField"),
            _col("churn_rate", "FloatDatabaseField"),
            _col("cohort_month", "DateDatabaseField"),
            _col("segment", "StringDatabaseField"),
        ),
        description_template="Analytics model: {entity}, materialized by the data-modeling layer.",
    ),
)

# Plausible column descriptions, applied to ~30% of columns so descriptions are
# noisy — the description needle can't be found just by "the table that has one".
_COLUMN_DESCRIPTION_TEMPLATES: tuple[str, ...] = (
    "The {col} value as ingested from the source system.",
    "Primary {col} field used for joins and lookups.",
    "Denormalized {col} copied from the upstream record.",
    "Audit field tracking {col} for this row.",
)


class WarehouseSchemaSynthesizer:
    """Deterministic generator. All randomness flows from ``seed``."""

    def __init__(self, *, seed: int = DEFAULT_NAME_SEED, noise_table_count: int = 250) -> None:
        self._providers: NameProviders = make_name_providers(seed)
        self._rnd = self._providers.rnd
        self._noise_table_count = noise_table_count

    def generate(self) -> SynthWarehouse:
        # Reserve needle names up front so noise generation can never collide.
        reserved = {
            DESC_NEEDLE_TABLE,
            TYPE_NEEDLE_TABLE,
            REL_NEEDLE_SOURCE,
            REL_NEEDLE_TARGET,
            RETRIEVAL_NEEDLE_TABLE,
            RELEVANCY_NEEDLE_CURRENT,
            RELEVANCY_NEEDLE_STALE,
            CHAIN_NEEDLE_HOP3,
        }
        noise_tables = self._generate_noise_tables(reserved)
        needles, needle_tables, needle_views, needle_joins = self._generate_needles()
        views = (*self._generate_noise_views(), *needle_views)
        warehouse = SynthWarehouse(
            tables=(*noise_tables, *needle_tables),
            views=views,
            joins=tuple(needle_joins),
            needles=needles,
        )
        self._validate(warehouse)
        return warehouse

    # -- noise ---------------------------------------------------------------

    def _generate_noise_tables(self, reserved: set[str]) -> list[SynthTable]:
        names: set[str] = set(reserved)
        tables: list[SynthTable] = []
        domains = list(_DOMAINS)
        per_domain = self._noise_table_count // len(domains)
        for domain in domains:
            tables.extend(self._generate_domain_tables(domain, per_domain, names))
        return tables

    def _generate_domain_tables(self, domain: _Domain, count: int, names: set[str]) -> list[SynthTable]:
        tables: list[SynthTable] = []
        suffixes = ("", "_v2", "_archive", "_staging", "_2022", "_2023", "_2024", "_raw", "_history")
        attempts = 0
        while len(tables) < count and attempts < count * 20:
            attempts += 1
            entity = self._rnd.choice(domain.entities)
            suffix = self._rnd.choice(suffixes)
            name = f"{domain.prefix}{entity}{suffix}"
            if name in names:
                continue
            names.add(name)
            tables.append(
                SynthTable(
                    name=name,
                    domain=domain.key,
                    columns=self._generate_columns(domain, entity),
                    description=domain.description_template.format(entity=entity.replace("_", " ")),
                    row_count=self._rnd.randint(100, 5_000_000),
                )
            )
        return tables

    def _generate_columns(self, domain: _Domain, entity: str) -> tuple[SynthColumn, ...]:
        pool = list(domain.column_pool)
        n = min(self._rnd.randint(3, 20), len(pool))
        chosen = self._rnd.sample(pool, n)
        out: list[SynthColumn] = []
        for col in chosen:
            description = None
            if self._rnd.random() < 0.3:
                template = self._rnd.choice(_COLUMN_DESCRIPTION_TEMPLATES)
                description = template.format(col=col.name)
            out.append(SynthColumn(name=col.name, hogql=col.hogql, nullable=col.nullable, description=description))
        return tuple(out)

    def _generate_noise_views(self) -> tuple[SynthView, ...]:
        return (
            SynthView(
                name="stg_stripe_charges",
                columns=(_col("id", "StringDatabaseField"), _col("amount", "IntegerDatabaseField")),
                sql="SELECT id, amount FROM stripe_charges",
                description="Staging model cleaning raw Stripe charges.",
            ),
            SynthView(
                name="dim_customers",
                columns=(_col("customer_id", "StringDatabaseField"), _col("email", "StringDatabaseField")),
                sql="SELECT customer_id, email FROM stripe_customers",
                description="Customer dimension keyed by Stripe customer id.",
            ),
            SynthView(
                name="fct_subscriptions",
                columns=(_col("subscription_id", "StringDatabaseField"), _col("mrr", "FloatDatabaseField")),
                sql="SELECT id AS subscription_id, amount AS mrr FROM stripe_subscriptions",
                description="Subscription fact table with one row per active subscription.",
            ),
        )

    # -- needles -------------------------------------------------------------

    def _generate_needles(
        self,
    ) -> tuple[dict[str, NeedleSpec], list[SynthTable], list[SynthView], list[SynthJoin]]:
        tables: list[SynthTable] = []
        views: list[SynthView] = []
        joins: list[SynthJoin] = []

        # A — found only by description (opaque name, generic columns).
        tables.append(
            SynthTable(
                name=DESC_NEEDLE_TABLE,
                domain="postgres_replica",
                columns=(
                    _col("id", "IntegerDatabaseField", nullable=False),
                    _col("account_id", "StringDatabaseField"),
                    _col("snapshot_date", "DateDatabaseField"),
                    _col("value", "FloatDatabaseField"),
                    _col("kind", "StringDatabaseField"),
                    _col("meta", "StringJSONDatabaseField"),
                ),
                description=(
                    f"Stores the per-account monthly recurring revenue snapshot used for the board "
                    f"revenue report. This is the {DESC_NEEDLE_PHRASE} for MRR — do not use "
                    f"stripe_invoices for MRR."
                ),
                row_count=self._rnd.randint(1_000, 50_000),
            )
        )

        # B — found by column data_type (the only Decimal column anywhere; warehouse
        # columns can't be UUID, so Decimal is the rare, distinctive type here).
        tables.append(
            SynthTable(
                name=TYPE_NEEDLE_TABLE,
                domain="hubspot",
                columns=(
                    _col("hs_object_id", "StringDatabaseField"),
                    _col(TYPE_NEEDLE_COLUMN, "DecimalDatabaseField"),
                    _col("region_geojson", "StringJSONDatabaseField"),
                    _col("synced_at", "DateTimeDatabaseField"),
                ),
                description="HubSpot sync metadata, including the high-precision FX rate used for currency conversion.",
                row_count=self._rnd.randint(100, 10_000),
            )
        )

        # C — reachable only via a relationship (join surfaced in relationships).
        rel_columns = (
            _col("id", "IntegerDatabaseField", nullable=False),
            _col(REL_NEEDLE_KEY, "StringDatabaseField"),
            _col("order_total", "FloatDatabaseField"),
            _col("ordered_at", "DateTimeDatabaseField"),
        )
        tables.append(
            SynthTable(
                name=REL_NEEDLE_SOURCE,
                domain="postgres_replica",
                columns=rel_columns,
                description="Orders placed in 2023, keyed to Salesforce accounts via account_ref.",
                row_count=self._rnd.randint(10_000, 500_000),
            )
        )
        tables.append(
            SynthTable(
                name=REL_NEEDLE_TARGET,
                domain="salesforce",
                columns=(
                    _col(REL_NEEDLE_KEY, "StringDatabaseField"),
                    _col("company_name", "StringDatabaseField"),
                    _col("industry", "StringDatabaseField"),
                    _col(CHAIN_NEEDLE_KEY, "StringDatabaseField"),  # FK to the owners table (second hop)
                ),
                description="Cross-reference mapping order account_ref to Salesforce company records.",
                row_count=self._rnd.randint(1_000, 50_000),
            )
        )
        joins.append(
            SynthJoin(
                source_table=REL_NEEDLE_SOURCE,
                source_key=REL_NEEDLE_KEY,
                joining_table=REL_NEEDLE_TARGET,
                joining_key=REL_NEEDLE_KEY,
                field_name=REL_NEEDLE_FIELD,
            )
        )

        # C2 — second join hop, so the agent must traverse relationships twice:
        # pg_orders_2023 -> salesforce_acct_xref -> salesforce_acct_owners.
        tables.append(
            SynthTable(
                name=CHAIN_NEEDLE_HOP3,
                domain="salesforce",
                columns=(
                    _col(CHAIN_NEEDLE_KEY, "StringDatabaseField"),
                    _col("owner_name", "StringDatabaseField"),
                    _col("region", "StringDatabaseField"),
                ),
                description="Salesforce account owners, keyed by owner_id; the account xref links here on owner_id.",
                row_count=self._rnd.randint(100, 5_000),
            )
        )
        joins.append(
            SynthJoin(
                source_table=REL_NEEDLE_TARGET,
                source_key=CHAIN_NEEDLE_KEY,
                joining_table=CHAIN_NEEDLE_HOP3,
                joining_key=CHAIN_NEEDLE_KEY,
                field_name=CHAIN_NEEDLE_FIELD,
            )
        )

        # F — relevancy: two identical-schema accounts dimensions; only the annotation
        # says which is live vs frozen. A naive name/schema scan can't disambiguate.
        relevancy_columns = (
            _col("account_id", "StringDatabaseField"),
            _col("company_name", "StringDatabaseField"),
            _col("industry", "StringDatabaseField"),
            _col("plan", "StringDatabaseField"),
            _col("seats", "IntegerDatabaseField"),
            _col("signed_up_at", "DateTimeDatabaseField"),
            _col("is_active", "BooleanDatabaseField"),
        )
        tables.append(
            SynthTable(
                name=RELEVANCY_NEEDLE_CURRENT,
                domain="postgres_replica",
                columns=relevancy_columns,
                description=(
                    "Live accounts dimension, refreshed daily — the canonical accounts source for "
                    f"current reporting. Replaced the frozen {RELEVANCY_NEEDLE_STALE}."
                ),
                row_count=self._rnd.randint(10_000, 80_000),
            )
        )
        tables.append(
            SynthTable(
                name=RELEVANCY_NEEDLE_STALE,
                domain="postgres_replica",
                columns=relevancy_columns,
                description=(
                    "DEPRECATED point-in-time accounts snapshot frozen at the end of 2023; no longer "
                    f"refreshed. Superseded by {RELEVANCY_NEEDLE_CURRENT} — do not use for current reporting."
                ),
                row_count=self._rnd.randint(10_000, 80_000),
            )
        )

        # D — the discovery-target view ("model").
        views.append(
            SynthView(
                name=VIEW_NEEDLE_NAME,
                columns=(
                    _col("date_day", "DateDatabaseField"),
                    _col("mrr", "FloatDatabaseField"),
                    _col("active_customers", "IntegerDatabaseField"),
                ),
                sql=(
                    "SELECT toDate(created) AS date_day, sum(amount) / 100.0 AS mrr, "
                    "count(DISTINCT customer_id) AS active_customers "
                    "FROM stripe_charges GROUP BY date_day"
                ),
                description="Daily MRR and active-customer counts; the model the finance dashboard reads.",
            )
        )

        # E — queryable duck-typing needle: all columns declared String, content lies.
        # Amounts are chosen so the *string* max ("9990") differs from the *numeric*
        # max (24990) — getting the right max requires casting text to a number, not
        # trusting the declared String type.
        retrieval_rows = (
            ("evt_001", "1990", '{"plan":"pro","seats":3}', "false"),
            ("evt_002", "24990", '{"plan":"standard","seats":12}', "false"),
            (
                RETRIEVAL_NEEDLE_EVENT_ID,
                "4990",
                f'{{"plan":"enterprise","seats":42,"secret_code":"{RETRIEVAL_NEEDLE_ANSWER}"}}',
                "false",
            ),
            ("evt_004", "0", '{"plan":"free","seats":1}', "true"),
            ("evt_005", "9990", '{"plan":"pro","seats":2}', "false"),
        )
        tables.append(
            SynthTable(
                name=RETRIEVAL_NEEDLE_TABLE,
                domain="stripe",
                columns=(
                    _col("event_id", "StringDatabaseField"),
                    _col("amount", "StringDatabaseField"),
                    _col("payload", "StringDatabaseField"),
                    _col("is_test", "StringDatabaseField"),
                ),
                description="Raw Stripe webhook events; values are stored verbatim as text.",
                queryable=True,
                rows=retrieval_rows,
                row_count=len(retrieval_rows),
            )
        )

        needles: dict[str, NeedleSpec] = {
            "description": NeedleSpec(
                kind="description",
                answer=DESC_NEEDLE_TABLE,
                target_table=DESC_NEEDLE_TABLE,
                distinguishing_phrase=DESC_NEEDLE_PHRASE,
            ),
            "column_type": NeedleSpec(
                kind="column_type",
                answer={"table": TYPE_NEEDLE_TABLE, "column": TYPE_NEEDLE_COLUMN},
                target_table=TYPE_NEEDLE_TABLE,
            ),
            "relationship": NeedleSpec(
                kind="relationship",
                answer=REL_NEEDLE_TARGET,
                relationship=(REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET),
            ),
            "view": NeedleSpec(kind="view", answer=VIEW_NEEDLE_NAME, target_view=VIEW_NEEDLE_NAME),
            "retrieval": NeedleSpec(
                kind="retrieval",
                answer=RETRIEVAL_NEEDLE_ANSWER,
                target_table=RETRIEVAL_NEEDLE_TABLE,
                queryable=True,
            ),
            "relevancy": NeedleSpec(
                kind="relevancy",
                answer=RELEVANCY_NEEDLE_CURRENT,
                target_table=RELEVANCY_NEEDLE_CURRENT,
                secondary_table=RELEVANCY_NEEDLE_STALE,
            ),
            "chain": NeedleSpec(
                kind="chain",
                answer=CHAIN_NEEDLE_HOP3,
                chain=(REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET, CHAIN_NEEDLE_HOP3),
            ),
        }
        return needles, tables, views, joins

    # -- validation ----------------------------------------------------------

    def _validate(self, warehouse: SynthWarehouse) -> None:
        """Guard the invariants the needles and scorers depend on."""
        names = [t.name for t in warehouse.tables]
        assert len(names) == len(set(names)), "duplicate table names generated"

        # Exactly one Decimal column in the whole catalog (the column-type needle).
        decimal_tables = [t.name for t in warehouse.tables for c in t.columns if c.hogql == "DecimalDatabaseField"]
        assert decimal_tables == [TYPE_NEEDLE_TABLE], f"Decimal column must be unique to needle, got {decimal_tables}"

        # The relationship join's endpoints must both exist as tables.
        table_names = set(names)
        for join in warehouse.joins:
            assert join.source_table in table_names, f"join source {join.source_table} missing"
            assert join.joining_table in table_names, f"join target {join.joining_table} missing"

        # Relevancy decoys: both accounts dimensions exist with identical schema, so
        # only the annotation distinguishes them.
        relevancy = {
            t.name: t for t in warehouse.tables if t.name in (RELEVANCY_NEEDLE_CURRENT, RELEVANCY_NEEDLE_STALE)
        }
        assert set(relevancy) == {RELEVANCY_NEEDLE_CURRENT, RELEVANCY_NEEDLE_STALE}, "relevancy pair missing"
        assert relevancy[RELEVANCY_NEEDLE_CURRENT].columns == relevancy[RELEVANCY_NEEDLE_STALE].columns, (
            "relevancy decoys must share an identical schema"
        )

        # Chain: the two-hop join path must be fully wired (orders -> xref -> owners).
        chain_edges = {(j.source_table, j.joining_table) for j in warehouse.joins}
        assert (REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET) in chain_edges, "chain hop 1 missing"
        assert (REL_NEEDLE_TARGET, CHAIN_NEEDLE_HOP3) in chain_edges, "chain hop 2 missing"

        # Exactly one queryable table (the retrieval needle).
        queryable = [t.name for t in warehouse.tables if t.queryable]
        assert queryable == [RETRIEVAL_NEEDLE_TABLE], f"expected one queryable table, got {queryable}"
