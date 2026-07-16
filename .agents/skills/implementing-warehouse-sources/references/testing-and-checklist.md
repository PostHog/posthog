# Testing expectations and implementation checklist

## Testing expectations

Add at least two test modules:

- `tests/test_<source>_source.py` (source-class level):
  - `source_type`
  - `get_source_config` fields and labels
  - `get_schemas` outputs
  - `validate_credentials` success/failure
  - `source_for_pipeline` argument plumbing
  - for resumable sources: `get_resumable_source_manager` returns a manager bound to the right data class
  - for webhook sources: `create_webhook` / `delete_webhook` / `get_external_webhook_info` behavior, `webhook_resource_map` correctness, `webhook_template` presence
- `tests/test_<source>.py` (transport level):
  - paginator behavior from response headers/body
  - resource generation for incremental vs non-incremental
  - endpoint-specific primary key mapping
  - credential validation status mapping
  - mapper/filter helpers if present
  - fan-out endpoint row format assertions (dict shape + parent identifiers)
  - for dependent-resource fan-out: mock `rest_api_resources`, pass rows with `_<parent>_<field>` keys to exercise parent-field injection and rename behavior
  - expected return schema checks for each declared endpoint in `settings.py`
  - for resumable sources: resume-from-saved-state path (manager returns state, transport uses it as starting point); state is saved after each batch
  - for incremental cursor pagination: the paginator stops once a page predates the watermark, and keeps walking when no watermark is set (first sync)

Prefer behavior tests over config-shape tests. Avoid brittle assertions on internal config dict structure unless they protect a known regression that cannot be asserted via output behavior.

Use parameterized tests for status codes and edge cases. Lean toward over-covering.

## Implementation checklist

```text
Bootstrapping:
- [ ] Enum added to products/warehouse_sources/backend/types.py (ALL_CAPS, no underscores between words)
- [ ] Entry added to frontend/src/queries/schema/schema-general.ts (kebab-case) — `pnpm run schema:build` regenerates posthog/schema.py from this; don't hand-edit posthog/schema.py
- [ ] Source imported in products/warehouse_sources/backend/temporal/data_imports/sources/__init__.py + __all__
- [ ] Class inherits from SimpleSource / ResumableSource / WebhookSource (or combo) — see "Picking the right base class" in ../SKILL.md

Source implementation:
- [ ] Set category on get_source_config (required — DataWarehouseSourceCategory; groups the source in the wizard catalog)
- [ ] Add keywords if the source has a common acronym / alternate spelling (optional, lowercase)
- [ ] Set api_docs_url (https, vendor API docs/changelog); add supported_versions + default_version if the vendor
      exposes a real version token — pin what the code actually calls (see "Vendor API version metadata" in source-config.md)
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

Release status (a finished source has NO unreleasedSource flag — it hides the source from users entirely):
- [ ] REQUIRED: delete `unreleasedSource=True` from the finished source (the scaffolded stub ships with it).
      Not being able to curl the live API is NOT a reason to keep it — use releaseStatus=ALPHA.
      Keep it ONLY when the code genuinely can't sync yet (landed across multiple PRs).
- [ ] No test asserts `unreleasedSource is True` (that anti-pattern locks the source hidden)
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
