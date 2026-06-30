# Canonical descriptions and the public table catalog

## Canonical descriptions (semantic enrichment)

After a table syncs, a background activity (`workflow_activities/enrich_table_semantics.py`) writes
`WarehouseColumnAnnotation` rows describing each table/column, surfaced to the AI agent. For
fixed-schema sources (SaaS APIs) the schema is the same for everyone, so document it **once** from the
official API docs instead of paying an LLM to re-derive it per team. These curated descriptions are
authoritative — they're applied directly (`description_source="canonical"`) and never sent to the LLM.

Add a `canonical_descriptions.py` **accompanying the source** (sibling of `source.py` / `settings.py`):

```python
# products/warehouse_sources/backend/temporal/data_imports/sources/{source}/canonical_descriptions.py
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Charge": {  # key = ExternalDataSchema.name (the endpoint name from get_schemas / ENDPOINTS)
        "description": "A single attempt to move money into your account by charging a payment source.",
        "docs_url": "https://stripe.com/docs/api/charges",  # passed to the LLM for columns not covered here
        "columns": {  # column name -> one-line description, taken from the official API docs
            "id": "Unique identifier for the charge.",
            "amount": "Amount intended to be collected, in the smallest currency unit (e.g. cents).",
        },
    },
}
```

Then override the hook on the source class with a lazy import of the sibling file:

```python
def get_canonical_descriptions(self) -> CanonicalDescriptions:
    from products.warehouse_sources.backend.temporal.data_imports.sources.{source}.canonical_descriptions import CANONICAL_DESCRIPTIONS
    return CANONICAL_DESCRIPTIONS
```

Rules:

- Key entries by the **endpoint/schema name** `get_schemas` returns (matches `ENDPOINTS`), not the
  prefixed warehouse table name.
- Source descriptions from the **official API docs**, not guesses. Partial coverage is fine — any
  missing endpoint, column, or table-level `description` falls back to the LLM, which is given the
  source name, endpoint, `docs_url`, and column data types.
- Optional and only meaningful for fixed-schema sources. SQL sources (arbitrary user schemas) ship
  nothing — the base hook returns `{}`.
- Don't touch `source.py`/`settings.py` transport logic — this is purely additive metadata.

## Publishing the table catalog to public docs

The posthog.com docs render a **Supported tables** section via a `<SourceTables />` component fed by the
`public_source_configs` API, which calls `get_documented_tables()` on each source. The base
implementation lists tables from `get_schemas` (merged with `canonical_descriptions`) **only when the
source opts in**:

```python
class MySource(SimpleSource[MySourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
```

Set this to `True` **only** when `get_schemas` iterates a static endpoint catalog with **no I/O** — no
network, no DB, no credentials (the common fixed-schema SaaS pattern: `for endpoint in ENDPOINTS`). The
endpoint builds a placeholder config and calls `get_schemas` with no real credentials, so a source that
connects to discover schemas (SQL, file storage, MongoDB, ad platforms that list accounts) must leave
this `False` (the default) — otherwise it would try to connect to an empty host, hang, or close the DB
session. When `False`, the docs render a generic "discovered from your account" note instead.

The richer the table list, the better the docs — so pair this with `canonical_descriptions.py`
(table/column descriptions). Verify the rendered output via the API:
`GET /api/public_source_configs` → your source → `tables`.
