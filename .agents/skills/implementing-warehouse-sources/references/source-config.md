# Source configuration

Everything that shapes `get_source_config`, the connector's metadata, and how it presents to users and docs.

## Source fields (the form the user fills in)

Defined in `get_source_config.fields`. All field types live in `posthog/schema.py` and are unioned as `FieldType` in `products/warehouse_sources/backend/temporal/data_imports/sources/common/base.py`.

- `SourceFieldInputConfig` — basic input (`text`, `email`, `number`, `password`, `textarea`). Rendered as `<LemonInput />`.
- `SourceFieldSwitchGroupConfig` — toggle that reveals a sub-group of fields. Use for optional feature blocks.
- `SourceFieldSelectConfig` — dropdown. Options can carry sub-`fields` shown when selected (use for alternative auth methods — e.g. API key vs OAuth).
- `SourceFieldOauthConfig` — OAuth via `Integration` model. See [auth.md](auth.md).
- `SourceFieldFileUploadConfig` — file upload (JSON). Use `keys=["..."]` allow-list or `"*"`.
- `SourceFieldSSHTunnelConfig` — renders SSH tunnel sub-fields; adds `ssh_tunnel: SSHTunnel` to the config with helpers.

Guidelines:

- Multiple auth methods → `SourceFieldSelectConfig` with child `fields` per option.
- Optional toggles → `SourceFieldSwitchGroupConfig`.
- Confidential fields must use `SourceFieldInputConfigType.PASSWORD`. The serializer derives sensitive vs nonsensitive keys automatically from the field definitions — you do not need to maintain an allow-list elsewhere.

## Source category & keywords

Every source **must** set `category` on its `SourceConfig` — it groups the source in the new-source wizard
catalog (a category rail + tile grid). A test (`tests/test_source_categories.py`) fails if any registered
source has no category, so this is non-optional. Import the enum from `posthog.schema`:

```python
from posthog.schema import DataWarehouseSourceCategory
...
return SourceConfig(
    name=SchemaExternalDataSourceType.STRIPE,
    category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
    keywords=["billing", "subscriptions"],
    ...
)
```

Pick the single closest bucket. The enum members (note the triple underscore where the label has " & "):

- `DATABASES` — OLTP/OLAP databases, warehouses, data streams (Postgres, Snowflake, BigQuery, Kafka, …)
- `FILE_STORAGE` — object/file stores & file transfer (S3, Azure Blob, GCS, Google Drive, SFTP, …)
- `ADVERTISING` — ad platforms & mobile attribution (Google Ads, Meta Ads, Reddit Ads, Adjust, …)
- `MARKETING___EMAIL` — email/SMS/marketing automation (Klaviyo, Mailchimp, Braze, SendGrid, …)
- `CRM` — CRM & sales intelligence (HubSpot, Salesforce, Attio, Pipedrive, ZoomInfo, …)
- `SALES` — sales engagement/enablement, contracts (Salesloft, Outreach, Gong, DocuSign, …)
- `CUSTOMER_SUPPORT` — helpdesk/support/CX (Zendesk, Intercom, Freshdesk, Front, …)
- `PAYMENTS___BILLING` — payment processors & subscription billing (Stripe, Chargebee, PayPal, …)
- `FINANCE___ACCOUNTING` — accounting/ERP/expense/spend (QuickBooks, Xero, NetSuite, SAP ERP, …)
- `ANALYTICS` — product/web/marketing analytics & experimentation (Amplitude, Mixpanel, GA, …)
- `ENGINEERING___MONITORING` — dev tooling, CI, error/uptime monitoring, feature flags, identity/auth (GitHub, Datadog, Sentry, LaunchDarkly, Auth0, …)
- `PRODUCTIVITY` — project mgmt, docs, forms, scheduling (Notion, Airtable, Jira, Linear, Typeform, …)
- `HR___RECRUITING` — HRIS/ATS/payroll/people (Ashby, Greenhouse, BambooHR, Workday, Gusto, …)
- `COMMUNICATION` — messaging/meetings/telephony/social (Slack, Zoom, Microsoft Teams, Twilio, …)
- `E_COMMERCE` — online store/commerce (Shopify, WooCommerce, BigCommerce, …)

The category list is the source of truth in `frontend/src/queries/schema/schema-general.ts`
(`dataWarehouseSourceCategories`); `pnpm run schema:build` regenerates the Python `DataWarehouseSourceCategory`
enum. Adding a **new** category means editing that array and rebuilding — don't invent ad-hoc strings.

`keywords` is an optional list of lowercase search aliases — only add when the source has a common acronym or
alternate spelling a user might type (e.g. `["ga4", "ga"]`, `["sql server"]`, `["facebook ads"]`). Skip it when
the name already obviously matches; don't add noise.

## Vendor API version metadata

Every source declares three class attributes (on the source class body, alongside `lists_tables_without_credentials`)
describing the vendor's API version.
The framework (`common/base.py`) records the version each `ExternalDataSource` runs against so old pins keep working
and deprecations can be surfaced;
`sources/tests/test_source_versions.py` enforces the invariants below across every registered source, so a new
source that gets these wrong fails CI.

Two cases:

- **The vendor exposes a real, pinnable API version** — a URL path segment (`/v3/`, `/2/`), a required version
  header value (a dated `2022-11-28`), a dated query/version param, or a named release. Declare all three:

  ```python
  class MySource(SimpleSource[MySourceConfig]):
      supported_versions = ("v3",)          # opaque vendor labels — never parsed or ordered
      default_version = "v3"                 # stamped onto newly created sources; must be in supported_versions
      api_docs_url = "https://vendor.example/docs/api"   # API reference or changelog page (https, not the marketing site)
  ```

  Pin **the version the source's own code actually calls** (the base URL path, a version header, or a version
  constant in `settings.py` / `{source}.py`) — not the vendor's newest version. Examples already in the tree:
  GitHub `("2022-11-28",)` (dated header), HubSpot `("v3",)` (path), Klaviyo `("2024-10-15",)` (dated revision).

- **The vendor has no meaningful API versioning** — set only `api_docs_url`; leave `supported_versions` /
  `default_version` at the framework default (`("v1",)`, the `UNVERSIONED_API_VERSION` sentinel). A bare `/v1/`
  that has never changed and isn't a documented version choice is this case.

Rules:

- `default_version` must equal the single entry in `supported_versions`, and `api_docs_url` must be `https://`.
- Use the vendor's exact version string; never invent one.
- Don't hardcode a fallback version in the transport/request layer — resolve it from the source class
  (`self.resolve_api_version(inputs.api_version)`), which already falls back to `default_version`.
- Adding support for a **new** vendor version later, or **deprecating** an old one, is the
  `/warehouse-source-new-version` skill — not this one.

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

## Document required token scopes

If the API issues OAuth scopes or per-resource access tokens, declare every scope the source actually calls so users know what to grant — don't make them grant the full set defensively.

- **OAuth sources:** set `requiredScopes` on `SourceFieldOauthConfig` (space-separated string, matches the OAuth `scope` parameter format). The frontend diffs it against the integration's granted scopes and warns the user with a Reconnect action when any are missing.
- **Non-OAuth sources (PAT, API key):** there's no integration object to inspect, so list scopes in the `caption` instead. Captions render through `LemonMarkdown`, so backticks, bold, and links work.

## Icons

- Prefer SVG over PNG. Keep file size reasonable.
- Place in `frontend/public/services/` and reference as `/static/services/{name}.svg` in `iconPath`.
- If the source logo isn't already in the project, pull via [Logo.dev](https://docs.logo.dev/introduction). **Ask the user for the API key** — do not hardcode one. If the user hasn't provided one, surface that as a blocker rather than committing a placeholder.
