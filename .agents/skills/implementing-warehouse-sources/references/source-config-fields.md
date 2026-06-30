# Source config: category, keywords, and fields

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

## Source fields (the form the user fills in)

Defined in `get_source_config.fields`. All field types live in `posthog/schema.py` and are unioned as `FieldType` in `products/warehouse_sources/backend/temporal/data_imports/sources/common/base.py`.

- `SourceFieldInputConfig` — basic input (`text`, `email`, `number`, `password`, `textarea`). Rendered as `<LemonInput />`.
- `SourceFieldSwitchGroupConfig` — toggle that reveals a sub-group of fields. Use for optional feature blocks.
- `SourceFieldSelectConfig` — dropdown. Options can carry sub-`fields` shown when selected (use for alternative auth methods — e.g. API key vs OAuth).
- `SourceFieldOauthConfig` — OAuth via `Integration` model. See OAuth section.
- `SourceFieldFileUploadConfig` — file upload (JSON). Use `keys=["..."]` allow-list or `"*"`.
- `SourceFieldSSHTunnelConfig` — renders SSH tunnel sub-fields; adds `ssh_tunnel: SSHTunnel` to the config with helpers.

Guidelines:

- Multiple auth methods → `SourceFieldSelectConfig` with child `fields` per option.
- Optional toggles → `SourceFieldSwitchGroupConfig`.
- Confidential fields must use `SourceFieldInputConfigType.PASSWORD`. The serializer derives sensitive vs nonsensitive keys automatically from the field definitions — you do not need to maintain an allow-list elsewhere.
