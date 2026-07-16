---
name: implementing-warehouse-sources
description: Implement and extend PostHog Data warehouse import sources. Use when adding a new source under products/warehouse_sources/backend/temporal/data_imports/sources, adding datasets/endpoints to an existing source, or adding incremental sync, resumable imports, webhook ingestion, pagination, credentials validation, and source tests.
---

# Implementing Data warehouse sources

Use this skill when building or updating Data warehouse sources in `products/warehouse_sources/backend/temporal/data_imports/sources/`.

This entry point covers the decision guide and the end-to-end workflow.
Detailed implementation patterns live in `references/` — load the one you need when you reach that step.

## Read first

Before coding, read:

- `products/warehouse_sources/backend/temporal/data_imports/sources/source.template` (use the top-of-file TODOs as a starting reference, but verify target files against the current source implementations — the template can drift, e.g. it currently still points at the old `posthog/warehouse/types.py` path instead of `products/warehouse_sources/backend/types.py`)
- `products/warehouse_sources/backend/temporal/data_imports/sources/README.md`
- `products/warehouse_sources/backend/temporal/data_imports/sources/SOURCES.md` — inventory of every registered source with its communication method (HTTP / vendor SDK / gRPC / DB protocol / webhook) and tracked-transport state. Skim this first to see how similar sources are wired and what state today's source you're touching is in. **Keep it in sync** — see [references/transport.md](references/transport.md).
- `products/warehouse_sources/backend/temporal/data_imports/sources/common/base.py` — base classes (`SimpleSource`, `ResumableSource`, `WebhookSource`) and the `FieldType` union
- `products/warehouse_sources/backend/temporal/data_imports/sources/common/resumable.py` — `ResumableSourceManager`
- `products/warehouse_sources/backend/temporal/data_imports/sources/common/webhook_s3.py` — `WebhookSourceManager`
- 1 API source with `settings.py` + transport logic (e.g. klaviyo, github). For dependent-resource fan-out (parent→child with `type: "resolve"`), also read `products/warehouse_sources/backend/temporal/data_imports/sources/common/rest_source/__init__.py` and `config_setup.py` (e.g. `process_parent_data_item`, `make_parent_key_name`).
- For webhook-capable sources, read `products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py` as the reference implementation.

## Reference map

Load these as you reach each step of the workflow — each is a one-hop read:

- [references/source-config.md](references/source-config.md) — the source form fields, `category` & `keywords`, vendor API version metadata, canonical descriptions, publishing the table catalog to public docs, documenting token scopes, and icons.
- [references/fetching-data.md](references/fetching-data.md) — implementing `source_for_pipeline` (resumable + webhook patterns), incremental sync, pagination, top-level endpoints, fan-out, and retry/throttling.
- [references/transport.md](references/transport.md) — the required tracked HTTP / gRPC transports, connection host fields (credential retargeting), and keeping `SOURCES.md` in sync.
- [references/auth.md](references/auth.md) — OAuth configuration, `validate_credentials`, non-retryable errors, and mixins.
- [references/api-verification.md](references/api-verification.md) — the curl-against-the-live-API checklist to run before finalizing endpoint logic.
- [references/sql-sources.md](references/sql-sources.md) — multi-schema SQL database sources (Postgres, MSSQL, Snowflake, Redshift).
- [references/testing-and-checklist.md](references/testing-and-checklist.md) — testing expectations and the full implementation checklist.
- [references/common-pitfalls.md](references/common-pitfalls.md) — the catalog of common failure modes and their causes.

## Picking the right base class

Every new source **must** inherit from one (or a combination) of these:

- **`SimpleSource[Config]`** — default for straightforward pull-based APIs where each run fully iterates the endpoint.
- **`ResumableSource[Config, ResumableData]`** — **preferred for any new API-backed source whose underlying API supports resumption** (cursor/link-header pagination, time windows, offset tokens, or any other deterministic way to pick back up where we left off). If the API gives us a next-page token, a `Link` header, or a stable time filter, use `ResumableSource`. This lets Temporal resume after heartbeat timeouts without restarting from scratch. The manager persists state to Redis (24h TTL).
- **`WebhookSource[Config]`** — only when the source can push events to us (e.g. Stripe webhook endpoints). Typically combined with `ResumableSource` so the initial backfill is resumable and subsequent deltas come via webhook.

Combine by multiple inheritance when both apply, e.g.:

```python
class StripeSource(
    ResumableSource[StripeSourceConfig, StripeResumeConfig],
    WebhookSource[StripeSourceConfig],
    OAuthMixin,
):
    ...
```

Rule of thumb:

- Pull-only API, no cursor we can persist → `SimpleSource`.
- Pull-only API with any cursor/next-page/time-filter we can save between runs → `ResumableSource`.
- Source can call us back with change events → add `WebhookSource` on top of whichever pull base fits.

Databases and file-transfer sources (SFTP, S3) stay on `SimpleSource` unless there's a clear reason otherwise.

## End-to-end workflow for a new API source

Follow this order. Each step maps to TODOs in `source.template`.

1. **Survey the source.** Pick the endpoints a user will actually want. Cross-reference:
   - Airbyte: <https://airbyte.com/connectors> (connector pages often link to source code — useful reference)
   - Fivetran: <https://www.fivetran.com/connectors>
   - Stitch: <https://www.stitchdata.com/docs/integrations/>
     Find the official API docs or OpenAPI spec. Make sure it's the current version, not a deprecated one.
2. **Bootstrap the source.** Copy the template and wire up the enum/type references:

   ```sh
   mkdir -p products/warehouse_sources/backend/temporal/data_imports/sources/{SOURCE_NAME}
   cp products/warehouse_sources/backend/temporal/data_imports/sources/source.template products/warehouse_sources/backend/temporal/data_imports/sources/{SOURCE_NAME}/source.py
   ```

   Then update the two hand-edited files (the template still lists `posthog/schema.py` too, but that file is regenerated by `pnpm run schema:build` in step 12 — don't maintain it by hand):
   - `ExternalDataSourceType` at `products/warehouse_sources/backend/types.py` — follow the existing convention in that file: `ALL_CAPS` with **no underscores** between words (e.g. `ACTIVECAMPAIGN`, `APPLESEARCHADS`), value is `PascalCase`
   - `externalDataSources` at `frontend/src/queries/schema/schema-general.ts` (`lower-kebab-case`)

3. **Pick the base class** (see above) and rename the class / `source_type` return.
4. **Define `get_source_config`** — name, **category** (required), label, caption, docsUrl, iconPath, fields, and optional `keywords`. Set the vendor API version metadata class attributes too. See [references/source-config.md](references/source-config.md).
5. **Register** the source — add an import line to `products/warehouse_sources/backend/temporal/data_imports/sources/__init__.py` and include it in `__all__`. (The `@SourceRegistry.register` decorator on the class handles runtime registration.)
6. **Run the config generator**: `pnpm run generate:source-configs`. Confirm the new config class appears in `products/warehouse_sources/backend/temporal/data_imports/sources/generated_configs.py`. **Do not edit that file by hand.** Every time you change `get_source_config.fields`, re-run the generator.
7. **Swap the generic `Config` type** in `source.py` for the generated `{Source}SourceConfig` class.
8. **Implement**: `validate_credentials`, `get_schemas`, `source_for_pipeline` (plus `get_resumable_source_manager` / `get_webhook_source_manager` as needed). See [references/fetching-data.md](references/fetching-data.md) and [references/auth.md](references/auth.md).
9. **Split transport logic.** Put API client, paginator, row normalization, and `SourceResponse` assembly in `{source}.py`. Keep endpoint catalog/incremental fields/primary keys/partition defaults in `settings.py`. See "Source architecture contract" below.
10. **Add icon.** Place at `frontend/public/services/{source}.svg` (prefer SVG). If the logo isn't already committed, fetch from [Logo.dev](https://docs.logo.dev/introduction) — **ask the user for the Logo.dev API key**; do not hardcode one. Keep file size reasonable. See [references/source-config.md](references/source-config.md).
11. **Run migrations.** `DEBUG=1 python manage.py makemigrations && DEBUG=1 ./bin/migrate` (only needed if a new enum value triggers a Django migration).
12. **Rebuild schema types**: `pnpm run schema:build`. This updates `posthog/schema.py` from `schema-general.ts` and makes the source appear in frontend dropdowns. Re-run whenever `schema-general.ts` changes.
13. **Release status — a finished source has no `unreleasedSource` flag.** A completed, working source ships visible and connectable, and the scaffolded stub ships with `unreleasedSource=True` pre-set, so **deleting that line is a mandatory part of finishing the source**. `unreleasedSource=True` **hides the connector from users entirely** (see `DataWarehouseQueryVariant.tsx`, `InlineSourceSetup.tsx`, `nonHogFunctionTemplatesLogic.tsx`).

    Deleting the line is **not** gated on anything you can't do in your environment — "I couldn't curl the live API" is NOT a reason to keep it. That's what `releaseStatus=ReleaseStatus.ALPHA` is for (a soft "new, lightly tested" label on a _visible_ source). The only legitimate reason to keep `unreleasedSource=True` is when the source physically cannot sync yet because it's being landed across several PRs. A source with working `get_schemas` / `source_for_pipeline` and passing tests is finished — the flag comes out. **Never write a test that asserts `unreleasedSource is True`** — that locks the bug in.

    A newly finished, tested source ships with:
    - **no `unreleasedSource`** (visible and connectable),
    - `releaseStatus=ReleaseStatus.ALPHA` for a new source that hasn't been extensively tested (`ReleaseStatus.BETA` once rough edges are ironed out; `ReleaseStatus.GA`, or omit `releaseStatus` entirely, for general availability),
    - optional `featureFlag="dwh-{source_name}"` (kebab-case) **only** if you want a controlled rollout to flagged users instead of releasing to everyone.

    Whenever you set `releaseStatus`, use the `ReleaseStatus` enum from `posthog.schema` — never a bare string literal. Add `ReleaseStatus` to your existing `from posthog.schema import (...)` block.

14. **Document the source.** Write or update the user-facing doc on posthog.com following the
    `/documenting-warehouse-sources` skill (template, shared snippets, `<SourceParameters />` +
    `<SourceTables />`). Ensure `docsUrl` in `get_source_config` matches the doc filename
    (kebab-case), and — if `get_schemas` is a static endpoint catalog — set
    `lists_tables_without_credentials = True` (see [references/source-config.md](references/source-config.md)) so the doc's Supported tables section
    renders. A finished source ships with a consistent doc, not a stub.
15. **Delete the template TODO comments** before PR.

## Source architecture contract

For API-backed sources, use this split:

- `source.py`: source registration, source form fields, schema list, credential validation, resumable/webhook manager wiring, pipeline handoff.
- `settings.py`: endpoint catalog, incremental fields, primary key, partition defaults.
- `{source}.py`: API client/auth, paginator, request params, row normalization, and `SourceResponse`.

This keeps endpoint behavior declarative and easy to extend.

For REST sources that mix top-level and fan-out endpoints, keep endpoint metadata in `settings.py` and route in `{source}.py` with this priority:

1. endpoint-specific custom iterators (only when required),
2. generic fan-out helper path,
3. top-level endpoint path.

## Required coding conventions

- Register with `@SourceRegistry.register`.
- Inherit `SimpleSource[GeneratedConfig]` unless resumable/webhook behavior is required (see "Picking the right base class").
- API sources should usually return `table_format="delta"` in endpoint resources.
- `primary_keys` are endpoint-specific (declare in `settings.py`, not always `id`). Use composite keys when no single field is unique. **The key must be unique across the whole table, not per parent**: fan-out child endpoints aggregate rows from every parent, so include the parent identifier in the key (e.g. `["form_id", "token"]`) unless the API explicitly documents global uniqueness. Non-unique keys seed duplicate rows in the Delta table, and every later merge multi-matches them — merges get slower each sync until the pod OOMs.
- Add partitioning for new sources where possible:
  - API sources: `partition_mode="datetime"` with a **stable** datetime field.
  - Database sources: `partition_count` and `partition_size`.
- Pick a partition key that **does not change** — `created_at`, `dateCreated`, `firstSeen`. Never use `updated_at` or `lastSeen`.
- Add `get_non_retryable_errors()` for known permanent failures (401/403, invalid/expired credentials, missing scopes).
- Keep comments minimal and only when intent is not obvious.
- Python imports at the top of the module, not inside functions (unless needed to break circular imports).

## Validation and generation workflow

After changing source fields, re-run `pnpm run generate:source-configs` and `pnpm run schema:build`, then the targeted tests for the new source. Run `ruff check . --fix` and `ruff format .` on modified Python files.
