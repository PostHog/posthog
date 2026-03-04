---
name: implementing-warehouse-sources
description: Implement and extend PostHog Data warehouse import sources. Use when adding a new source under posthog/temporal/data_imports/sources, adding datasets/endpoints to an existing source, or adding incremental sync support, pagination, credentials validation, and source tests.
---

# Implementing Data warehouse sources

Use this skill when building or updating Data warehouse sources in `posthog/temporal/data_imports/sources/`.

## Read first

Before coding, read:

- `posthog/temporal/data_imports/sources/source.template`
- `posthog/temporal/data_imports/sources/README.md`
- 1 API source with `settings.py` + transport logic, for example:
  - `posthog/temporal/data_imports/sources/klaviyo/settings.py`
  - `posthog/temporal/data_imports/sources/klaviyo/klaviyo.py`
  - `posthog/temporal/data_imports/sources/github/settings.py`
  - `posthog/temporal/data_imports/sources/github/github.py`

## Source architecture contract

For API-backed sources, use this split:

- `source.py`: source registration, source form fields, schema list, credential validation, and pipeline handoff.
- `settings.py`: endpoint catalog, incremental fields, primary key and partition defaults.
- `{source}.py`: API client/auth, paginator, request params, row normalization, and `SourceResponse`.

This keeps endpoint behavior declarative and easy to extend.

## Implementation checklist

Copy this and track progress:

```text
Source implementation:
- [ ] Define source fields in `get_source_config`
- [ ] Implement credential validation
- [ ] Define schemas in `get_schemas`
- [ ] Add/confirm endpoint settings (`settings.py`)
- [ ] Implement transport and paginator (`{source}.py`)
- [ ] Return correct `SourceResponse` (keys, partitioning, sort mode)
- [ ] Add non-retryable auth/permission errors
- [ ] Add source tests
- [ ] Add transport tests
- [ ] Add icon in `frontend/public/services/`
- [ ] Run `pnpm run generate:source-configs`
- [ ] Run `pnpm run schema:build`
```

## Required coding conventions

- Register with `@SourceRegistry.register`.
- Source class should inherit `SimpleSource[GeneratedConfig]` unless resumable/webhook behavior is required.
- Prefer explicit endpoint metadata in `settings.py` rather than hard-coded branches in transport logic.
- API sources should usually return `table_format="delta"` in endpoint resources.
- Use `primary_keys` for incremental merge safety.
- Add partitioning for new sources where possible:
  - API sources: `partition_mode="datetime"` with stable datetime field when available.
- Add `get_non_retryable_errors()` for known permanent failures (401/403/invalid credentials).
- Keep comments minimal and only when intent is not obvious.

## Incremental sync guidance

- If API supports server-side time filtering, add it and map from `db_incremental_field_last_value`.
- If API only supports cursor pagination, still declare incremental fields if reliable and let merge semantics dedupe.
- Set `sort_mode="desc"` only if the endpoint truly returns descending order and cannot return ascending.
- For descending sources, make sure behavior with `db_incremental_field_earliest_value` is considered.

## Testing expectations

Add at least two test modules:

- `tests/test_<source>_source.py`:
  - `source_type`
  - `get_source_config` fields and labels
  - `get_schemas` outputs
  - `validate_credentials` success/failure
  - `source_for_pipeline` argument plumbing
- `tests/test_<source>.py`:
  - paginator behavior from API response headers/body
  - resource generation for incremental vs non-incremental
  - credential validation status mapping
  - mapper/filter helpers if present

Use parameterized tests for status codes and edge cases.

## Validation and generation workflow

After changing source fields:

```bash
pnpm run generate:source-configs
pnpm run schema:build
```

Then run targeted tests for the new source.

## Common pitfalls

- Source not visible in wizard: source not registered/imported, or schema not rebuilt.
- Generated config class still empty: forgot `generate:source-configs` after updating fields.
- Incremental sync misbehaving: wrong field name/type or wrong sort assumptions.
- Endless retries for bad credentials: missing `get_non_retryable_errors`.
