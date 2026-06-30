---
name: implementing-warehouse-sources
description: Implement and extend PostHog Data warehouse import sources. Use when adding a new source under products/warehouse_sources/backend/temporal/data_imports/sources, adding datasets/endpoints to an existing source, or adding incremental sync, resumable imports, webhook ingestion, pagination, credentials validation, and source tests.
---

# Implementing Data warehouse sources

Use this skill when building or updating Data warehouse sources in `products/warehouse_sources/backend/temporal/data_imports/sources/`.

This file holds the core workflow, base-class guidance, and conventions you need on every source. Deeper, self-contained how-to material lives in `references/` — load a reference only when the step you're on needs it. See [Reference material](#reference-material) for the index.

## Read first

Before coding, read:

- `products/warehouse_sources/backend/temporal/data_imports/sources/source.template` (use the top-of-file TODOs as a starting reference, but verify target files against the current source implementations — the template can drift, e.g. it currently still points at the old `posthog/warehouse/types.py` path instead of `products/warehouse_sources/backend/types.py`)
- `products/warehouse_sources/backend/temporal/data_imports/sources/README.md`
- `products/warehouse_sources/backend/temporal/data_imports/sources/SOURCES.md` — inventory of every registered source with its communication method (HTTP / vendor SDK / gRPC / DB protocol / webhook) and tracked-transport state. Skim this first to see how similar sources are wired and what state today's source you're touching is in. **Keep it in sync** — see [references/sources-md.md](references/sources-md.md).
- `products/warehouse_sources/backend/temporal/data_imports/sources/common/base.py` — base classes (`SimpleSource`, `ResumableSource`, `WebhookSource`) and the `FieldType` union
- `products/warehouse_sources/backend/temporal/data_imports/sources/common/resumable.py` — `ResumableSourceManager`
- `products/warehouse_sources/backend/temporal/data_imports/sources/common/webhook_s3.py` — `WebhookSourceManager`
- 1 API source with `settings.py` + transport logic (e.g. klaviyo, github). For dependent-resource fan-out (parent→child with `type: "resolve"`), also read `products/warehouse_sources/backend/temporal/data_imports/sources/common/rest_source/__init__.py` and `config_setup.py` (e.g. `process_parent_data_item`, `make_parent_key_name`).
- For webhook-capable sources, read `products/warehouse_sources/backend/temporal/data_imports/sources/stripe/source.py` as the reference implementation.

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

The resumable and webhook implementation patterns (data-class shape, `save_state` timing, webhook manager wiring, batch de-dup) live in [references/resumable-and-webhook.md](references/resumable-and-webhook.md).

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
4. **Define `get_source_config`** — name, **category** (required), label, caption, docsUrl, iconPath, fields, and optional `keywords`. Category buckets, keyword guidance, and the field-type catalog are in [references/source-config-fields.md](references/source-config-fields.md).
5. **Register** the source — add an import line to `products/warehouse_sources/backend/temporal/data_imports/sources/__init__.py` and include it in `__all__`. (The `@SourceRegistry.register` decorator on the class handles runtime registration.)
6. **Run the config generator**: `pnpm run generate:source-configs`. Confirm the new config class appears in `products/warehouse_sources/backend/temporal/data_imports/sources/generated_configs.py`. **Do not edit that file by hand.** Every time you change `get_source_config.fields`, re-run the generator.
7. **Swap the generic `Config` type** in `source.py` for the generated `{Source}SourceConfig` class.
8. **Implement**: `validate_credentials`, `get_schemas`, `source_for_pipeline` (plus `get_resumable_source_manager` / `get_webhook_source_manager` as needed).
9. **Split transport logic.** Put API client, paginator, row normalization, and `SourceResponse` assembly in `{source}.py`. Keep endpoint catalog/incremental fields/primary keys/partition defaults in `settings.py`.
10. **Add icon.** Place at `frontend/public/services/{source}.svg` (prefer SVG). See [references/icons-and-mixins.md](references/icons-and-mixins.md) for sourcing logos.
11. **Run migrations.** `DEBUG=1 python manage.py makemigrations && DEBUG=1 ./bin/migrate` (only needed if a new enum value triggers a Django migration).
12. **Rebuild schema types**: `pnpm run schema:build`. This updates `posthog/schema.py` from `schema-general.ts` and makes the source appear in frontend dropdowns. Re-run whenever `schema-general.ts` changes.
13. **Release status — a finished source has no `unreleasedSource` flag.** The default for the deliverable this skill produces is **no `unreleasedSource`** — a completed, working source ships visible and connectable. You don't need anyone's sign-off to ship it released; that's just the finished state. The scaffolded stub ships with `unreleasedSource=True` pre-set, so deleting that line is part of finishing the source — go ahead and remove it. (Why it matters: `unreleasedSource=True` **hides the connector from users entirely** — the frontend filters out every source where it's truthy; see `DataWarehouseQueryVariant.tsx`, `InlineSourceSetup.tsx`, and the "coming soon / Notify me" path in `nonHogFunctionTemplatesLogic.tsx`.)

    Keeping `unreleasedSource=True` is the exception that needs a reason: only do it when the source is genuinely incomplete and must not be reachable yet (e.g. you're landing it across several PRs and it can't sync). The moment it syncs end-to-end and its tests pass, it's done — the flag comes out.

    So a newly finished, tested source ships with:
    - **no `unreleasedSource`** (visible and connectable),
    - `releaseStatus=ReleaseStatus.ALPHA` for a new source that hasn't been extensively tested (`ReleaseStatus.BETA` once rough edges are ironed out; `ReleaseStatus.GA`, or omit `releaseStatus` entirely, for general availability) — a soft label on a _visible_ source, not a gate,
    - optional `featureFlag="dwh-{source_name}"` (kebab-case) **only** if you want a controlled rollout to flagged users instead of releasing to everyone.

    Whenever you set `releaseStatus`, use the `ReleaseStatus` enum from `posthog.schema` — never a bare string literal. Add `ReleaseStatus` to your existing `from posthog.schema import (...)` block.

14. **Document the source.** Write or update the user-facing doc on posthog.com following the
    `/documenting-warehouse-sources` skill (template, shared snippets, `<SourceParameters />` +
    `<SourceTables />`). Ensure `docsUrl` in `get_source_config` matches the doc filename
    (kebab-case), and — if `get_schemas` is a static endpoint catalog — set
    `lists_tables_without_credentials = True` (see [references/canonical-descriptions.md](references/canonical-descriptions.md)) so the doc's Supported tables section
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

See [references/endpoints-and-pagination.md](references/endpoints-and-pagination.md) for the endpoint inventory workflow, top-level vs fan-out endpoint setup, and pagination tips.

## Implementing `source_for_pipeline`

Return a `SourceResponse` directly. **Do not** use `dlt_source_to_source_response` for new sources — DLT is being removed.

Prefer yielding data in the shape the API returns it. No custom dataclasses, no heavy parsing. Yield either `dict`, `list[dict]` (preferred when possible), or a `pyarrow.Table`. The pipeline buffers and batches for you.

**Don't import or instantiate `Batcher` at the source layer.** The pipeline already runs one (`pipelines/pipeline/pipeline.py`) at the same 5000-row / 200 MiB thresholds. Yielding raw `dict` / `list[dict]` from your generator is the canonical path — reach for `pyarrow.Table` only when you already have arrow-shaped data (e.g., a ClickHouse adapter). Source-level batching results in double-buffering with no behavioral win.

For pyarrow tables, cap in-memory rows at ~200 MiB or ~5000 rows. Use helpers like `table_from_iterator()` / `table_from_py_list()` from `products/warehouse_sources/backend/temporal/data_imports/pipelines/pipeline/utils.py`.

**URL construction:** use `urllib.parse.urlencode` for query strings. Don't use `requests.Request(...).prepare().url` — `PreparedRequest.url` is typed `Optional[str]` and the typical workaround (`prepared.url or f"..."`) carries an unreachable fallback. `urlencode` is shorter, dependency-free, and produces identical output for ASCII-safe params.

Resumable and webhook variants of `source_for_pipeline` are in [references/resumable-and-webhook.md](references/resumable-and-webhook.md).

All outbound traffic must go through the tracked transport — see [references/tracked-transport.md](references/tracked-transport.md) (HTTP and gRPC, CI-enforced) before writing any API client.

## Required coding conventions

- Register with `@SourceRegistry.register`.
- Inherit `SimpleSource[GeneratedConfig]` unless resumable/webhook behavior is required.
- API sources should usually return `table_format="delta"` in endpoint resources.
- `primary_keys` are endpoint-specific (declare in `settings.py`, not always `id`). Use composite keys when no single field is unique. **The key must be unique across the whole table, not per parent**: fan-out child endpoints aggregate rows from every parent, so include the parent identifier in the key (e.g. `["form_id", "token"]`) unless the API explicitly documents global uniqueness. Non-unique keys seed duplicate rows in the Delta table, and every later merge multi-matches them — merges get slower each sync until the pod OOMs.
- Add partitioning for new sources where possible:
  - API sources: `partition_mode="datetime"` with a **stable** datetime field.
  - Database sources: `partition_count` and `partition_size`.
- Pick a partition key that **does not change** — `created_at`, `dateCreated`, `firstSeen`. Never use `updated_at` or `lastSeen`.
- Add `get_non_retryable_errors()` for known permanent failures (401/403, invalid/expired credentials, missing scopes) — see [references/retries-and-errors.md](references/retries-and-errors.md).
- Keep comments minimal and only when intent is not obvious.
- Python imports at the top of the module, not inside functions (unless needed to break circular imports).

## Incremental sync guidance

- **Only set `supports_incremental=True` when the API exposes a server-side timestamp filter** (`<field>_gte`, `since`, `modified_after`, etc.). A "client-side cursor" that fetches every page and skips already-seen rows in Python is **not** incremental — every run still hits every page, so the API cost of an "incremental" sync ends up identical to a full refresh. If the API has no server filter, ship full refresh only.
- If the API supports server-side time filtering, use it and map from `db_incremental_field_last_value`.
- **Honor `inputs.incremental_field`** — that's the user's chosen cursor field from the schema settings. `INCREMENTAL_FIELDS` per-endpoint is the menu of _advertised options_; don't reach into `INCREMENTAL_FIELDS[endpoint][0]` to pick a default and silently override the user's selection.
- **Per-endpoint sort enums vary.** Don't hardcode `?sorting=created_at` (or whatever) globally. Verify each list endpoint's allowed sort values against the API spec **and** with a curl smoke-test against the live API — APIs frequently document one set of options and silently reject another, or use a different timestamp column on certain resources.
- **Pass `?sorting=` explicitly on a stable monotonic field when paginating.** For incremental sources, the request sort must match `SourceResponse.sort_mode` (`"asc"` typically; `"desc"` only when forced by the API — see `stripe/stripe.py`, `github/settings.py`) so the pipeline's cursor watermark advances correctly. For full-refresh sources, an explicit sort prevents page-boundary skips/duplicates if the API's implicit default is unstable or shifts as rows are inserted during the sync.
- If the API only supports cursor pagination, still declare incremental fields if reliable and let merge semantics dedupe.
- **`sort_mode` must match the order rows actually arrive in — verify it, don't assume it.** The pipeline trusts `sort_mode="asc"` to checkpoint the incremental watermark after every batch and to allow safe mid-sync worker shutdowns; declaring `asc` while the API returns newest-first corrupts the watermark and breaks resume semantics. Check the API's _default_ sort (it applies when you can't pass `sort`), and remember cursor pagination often rejects or ignores sort params entirely.
- `sort_mode="desc"` only if the endpoint truly cannot return ascending. For descending sources, handle `db_incremental_field_earliest_value` to scroll earlier rows before newer ones (see Stripe).
- **Incremental pagination must terminate at the watermark.** Some APIs reject mixing their time-window filter with cursor pagination, so only the first page is windowed and later pages walk back through history unbounded. If the server can't keep the filter on every page, the paginator must stop client-side once an entire page predates `db_incremental_field_last_value` (see `typeform/typeform.py:TypeformResponsesPaginator`) — otherwise **every incremental sync re-fetches and re-merges each parent's full history**, which is both an API-cost bug and a per-sync memory amplifier.
- Default unknown endpoints to full refresh first; enable incremental only after confirming a stable filter field and API ordering semantics.
- Confirm partition keys against response schemas, not endpoint names.

Verify these assumptions against the live API before shipping — see [references/api-verification.md](references/api-verification.md).

## Multi-schema SQL database sources

SQL DB sources (Postgres, MSSQL, Snowflake, Redshift) can import tables from every namespace in one connection. The capability marker is the `schema` field being optional. Full parity checklist, per-row routing rules, and naming-layer pitfalls are in [references/multi-schema-sql.md](references/multi-schema-sql.md).

## Reference material

Load these on demand — each is self-contained:

- [Source config: category, keywords & fields](references/source-config-fields.md) — `get_source_config` category buckets, keyword guidance, field-type catalog.
- [Resumable & webhook source patterns](references/resumable-and-webhook.md) — data-class shape, `save_state` timing, webhook manager wiring, batch de-dup.
- [Canonical descriptions & public table catalog](references/canonical-descriptions.md) — `canonical_descriptions.py`, `get_canonical_descriptions`, `lists_tables_without_credentials`.
- [Multi-schema SQL database sources](references/multi-schema-sql.md) — blank-namespace discovery, per-row routing, qualified naming.
- [Tracked outbound transport & connection host fields](references/tracked-transport.md) — `make_tracked_session`, tracked gRPC, `connection_host_fields` (all CI-enforced).
- [Updating SOURCES.md](references/sources-md.md) — when and how to keep the source inventory in sync.
- [Endpoint coverage: inventory, top-level, fan-out & pagination](references/endpoints-and-pagination.md) — endpoint inventory workflow, dependent resources, pagination tips.
- [Retries, throttling & non-retryable errors](references/retries-and-errors.md) — `tenacity` usage, `get_non_retryable_errors()`.
- [Credentials, OAuth & token scopes](references/credentials-and-oauth.md) — OAuth setup, `validate_credentials`, `get_endpoint_permissions`, `requiredScopes`.
- [Icons & mixins](references/icons-and-mixins.md) — icon placement/sourcing, `SSHTunnelMixin` / `OAuthMixin` / `ValidateDatabaseHostMixin`.
- [Testing expectations](references/testing.md) — required source-class and transport-level test modules.
- [API behavior verification checklist](references/api-verification.md) — what to confirm with curl before finalizing endpoint logic.

## Implementation checklist

```text
Bootstrapping:
- [ ] Enum added to products/warehouse_sources/backend/types.py (ALL_CAPS, no underscores between words)
- [ ] Entry added to frontend/src/queries/schema/schema-general.ts (kebab-case) — `pnpm run schema:build` regenerates posthog/schema.py from this; don't hand-edit posthog/schema.py
- [ ] Source imported in products/warehouse_sources/backend/temporal/data_imports/sources/__init__.py + __all__
- [ ] Class inherits from SimpleSource / ResumableSource / WebhookSource (or combo) — see "Picking the right base class"

Source implementation:
- [ ] Set category on get_source_config (required — DataWarehouseSourceCategory; groups the source in the wizard catalog)
- [ ] Add keywords if the source has a common acronym / alternate spelling (optional, lowercase)
- [ ] Define source fields in get_source_config
- [ ] Implement validate_credentials
- [ ] Implement get_schemas
- [ ] Add endpoint settings (settings.py)
- [ ] Implement transport + paginator ({source}.py)
- [ ] Return SourceResponse with correct primary_keys, partitioning, sort_mode
      (keys unique table-wide — parent id in fan-out child keys; sort_mode verified against actual response order;
      incremental cursor pagination stops at the watermark)
- [ ] Implement get_resumable_source_manager if ResumableSource
- [ ] Implement webhook methods if WebhookSource
- [ ] Add get_non_retryable_errors for auth/permission errors
- [ ] (Fixed-schema sources) Add canonical_descriptions.py from the API docs + override get_canonical_descriptions
- [ ] (Fixed-schema sources, static get_schemas only) Set lists_tables_without_credentials = True so public docs render the table catalog

Tooling & assets:
- [ ] Icon in frontend/public/services/ (SVG preferred — ask user for Logo.dev key if needed)
- [ ] Run `pnpm run generate:source-configs`
- [ ] Swap generic Config for generated {Source}SourceConfig in source.py
- [ ] Run `pnpm run schema:build`
- [ ] Django migrations run if enum value requires it

Release status (default: a finished source has NO unreleasedSource flag — it hides the source from users):
- [ ] No unreleasedSource on the finished source — delete the line the scaffolded stub ships with
      (keep it ONLY as an exception, when the source is genuinely incomplete / landed across multiple PRs)
- [ ] When set, releaseStatus uses the `ReleaseStatus` enum, never a string literal
- [ ] releaseStatus=ReleaseStatus.ALPHA for a new source not yet extensively tested
      (ReleaseStatus.BETA later; ReleaseStatus.GA or omit for GA)
- [ ] featureFlag="dwh-{source_name}" ONLY if you want a controlled rollout instead of releasing to all

Tests & handoff:
- [ ] Source tests (test_<source>_source.py)
- [ ] Transport tests (test_<source>.py)
- [ ] User-facing doc written/updated per /documenting-warehouse-sources (docsUrl matches filename; `audit_source_docs` passes)
- [ ] `ruff check . --fix` and `ruff format .`
- [ ] List any new env vars (OAuth client IDs/secrets, etc) in the PR / handoff
```

## Validation and generation workflow

After changing source fields, re-run `pnpm run generate:source-configs` and `pnpm run schema:build`, then the targeted tests for the new source. Run `ruff check . --fix` and `ruff format .` on modified Python files.

## Common pitfalls

- Source not visible in wizard: not registered/imported in `sources/__init__.py`, or `schema:build` not rerun.
- `test_source_categories` failing: the source's `get_source_config` is missing `category` — set it to the closest `DataWarehouseSourceCategory` bucket.
- Generated config class still empty: forgot `generate:source-configs` after updating fields.
- Incremental sync misbehaving: wrong field name/type or wrong sort assumptions.
- Pod OOMs on a busy table: primary key not actually unique (usually a fan-out child missing the parent id in its key) — duplicate rows accumulate and every merge multi-matches them; often paired with a paginator that re-walks full history each sync because the time filter only applies to page one.
- `sort_mode="asc"` declared on an API that returns newest-first: the watermark checkpoints to ≈now after the first batch and mid-sync shutdowns lose data ordering guarantees.
- Endless retries for bad credentials: missing `get_non_retryable_errors`.
- Source won't connect despite a valid token: `validate_credentials(schema_name=None)` probes every resource's scope instead of just the token, so one missing scope — often on a table the user won't sync — blocks the whole source. Probe only the token at create; report per-table scope via `get_endpoint_permissions`.
- Resumable state never saved: forgot to call `save_state` after yielding a batch; or saved before yield and a crash causes data loss.
- Webhook rows not landing: schema `is_webhook=False`, or `initial_sync_complete=False`.
- Dependent resource path `KeyError`: pre-format static path placeholders (see [references/endpoints-and-pagination.md](references/endpoints-and-pagination.md)).
- Silent truncation risk: page caps hit without logs/metrics.
- Drift from refactors: unused function params/helpers left behind after endpoint behavior changes.
- Type drift in endpoint config dicts: use source typing aliases (`Endpoint`, `ClientConfig`, `IncrementalConfig`) to keep static checks precise.
- Partition key instability: picked `updated_at` instead of `created_at`; partitions rewrite on every sync.
- Hardcoded Logo.dev key committed: always ask the user for the key at runtime.
