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
- 1 API source with `settings.py` + transport logic (e.g. klaviyo, github). For dependent-resource fan-out (parent→child with `type: "resolve"`), also read `posthog/temporal/data_imports/sources/common/rest_source/__init__.py` and `config_setup.py` (e.g. `process_parent_data_item`, `make_parent_key_name`).

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
- [ ] For Beta: set `betaSource=True` in `SourceConfig`; omit `unreleasedSource` (or set `False`) when releasing.
```

## Required coding conventions

- Register with `@SourceRegistry.register`.
- Source class should inherit `SimpleSource[GeneratedConfig]` unless resumable/webhook behavior is required.
- Prefer explicit endpoint metadata in `settings.py` rather than hard-coded branches in transport logic.
- API sources should usually return `table_format="delta"` in endpoint resources.
- Use `primary_keys` for incremental merge safety; they are endpoint-specific (declare in `settings.py`, not always `id`).
- Add partitioning for new sources where possible:
  - API sources: `partition_mode="datetime"` with stable datetime field when available.
- Add `get_non_retryable_errors()` for known permanent failures (401/403/invalid credentials).
- Keep comments minimal and only when intent is not obvious.

## Incremental sync guidance

- If API supports server-side time filtering, add it and map from `db_incremental_field_last_value`.
- If API only supports cursor pagination, still declare incremental fields if reliable and let merge semantics dedupe.
- Set `sort_mode="desc"` only if the endpoint truly returns descending order and cannot return ascending.
- For descending sources, make sure behavior with `db_incremental_field_earliest_value` is considered.
- Default unknown endpoints to full refresh first; only enable incremental after confirming a stable filter field and API semantics.
- Prefer immutable partition keys (`created_at`, `dateCreated`, `firstSeen`) over mutable fields (`updated_at`, `lastSeen`) when both exist.
- Confirm partition keys against response schemas, not assumptions from endpoint names.

## API behavior verification checklist

Before finalizing endpoint logic, verify these from docs (or reliable API examples):

- Response shape: list vs object vs wrapped data (`{"data": [...]}`).
- Pagination contract: Link header vs body cursor vs offset/page; next-page termination signal.
- Ordering guarantees: ascending/descending/undefined for key time fields.
- Rate limit headers and semantics (window reset timestamp, concurrent limits).
- Field stability: whether candidate incremental/partition fields can change over time.

If behavior is not documented, keep parsing/merge logic conservative and add a code comment documenting the uncertainty.

## Endpoint inventory workflow

- Build an endpoint inventory before expanding coverage:
  - endpoint path and auth scopes,
  - grain (org/project/child fan-out),
  - pagination style,
  - primary key shape (single/composite),
  - incremental candidate fields.
- Keep the inventory in source-local docs (for example `posthog/temporal/data_imports/sources/<source>/api_inventory.md`) so future endpoint additions stay consistent.
- Add endpoints in phases:
  - org-level list endpoints first,
  - then project-level fan-out,
  - then child/fan-out endpoints with bounded pagination.

## Pagination tips

- Some APIs use cursor pagination in `Link` headers — check both `rel="next"` and any results flag the API may use.
- When following a full cursor URL from response headers, clear request params in paginator `update_request` to avoid duplicate query params.
- For parent/child fan-out, keep hard page caps per parent resource to avoid unbounded scans.
- Emit structured logs when page caps are reached (include resource name and parent identifiers) so operators can tune limits safely.

## Retry and throttling strategy

- Use a retry framework (for example tenacity) instead of manual retry loops where possible.
- Retry transport failures and retryable status codes (`429`, transient `5xx`).
- Prefer server-provided rate-limit reset headers for wait calculation on `429`; fall back to exponential backoff when unavailable.
- Keep retries bounded and deterministic (`stop_after_attempt`), and preserve clear terminal behavior:
  - return final response for retried status responses when useful for downstream handling, or
  - raise final exception for transport failures.
- Keep timeout and retry settings near the top of the module for easy operator tuning.

## Fan-out endpoints

Fan-out means iterating a parent resource (for example projects) and then querying child endpoints per parent (for example project issues).

**Prefer dependent resources when you have a single parent→child.** Use `rest_api_resources` with a parent resource and a child that declares `type: "resolve"` for the parent field (e.g. parent slug or id). The shared infra (`rest_source/__init__.py`, `config_setup.process_parent_data_item`) paginates the parent and calls the child per parent row. Add `include_from_parent` so child rows get parent fields; they are injected as `_<parent>_<field>` via `make_parent_key_name`. Add a row mapper to rename those to the final column names (e.g. `project_id`, `project_slug`). Do not expose internal fan-out tuning knobs in the user-facing form; use internal defaults.

**Path pre-formatting:** Child paths often have multiple placeholders (e.g. org and resource slug). `process_parent_data_item` only does `str.format()` with the _resolved_ param. Pre-format any static placeholders with `.replace()` on the child path before passing to the resource config, so only the resolved placeholder remains and DLT does not raise `KeyError`.

**When to keep a custom iterator:** If fan-out requires two or more levels (e.g. parent → mid-level list → detail per mid-level), where an intermediate API call discovers values that become part of the URL, that cannot be expressed as a single parent→child in `rest_api_resources`. Implement a custom HTTP iterator for that endpoint only; reuse the same pagination/retry helpers as elsewhere.

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
  - endpoint-specific primary key mapping
  - credential validation status mapping
  - mapper/filter helpers if present
  - fan-out endpoint row format assertions (dict shape + parent identifiers)
  - for dependent-resource fan-out: mock `rest_api_resources`, pass rows with `_<parent>_<field>` keys to exercise the row mapper; optionally assert config shape
  - expected return schema checks for each declared endpoint in `settings.py`

Use parameterized tests for status codes and edge cases.

## Validation and generation workflow

After changing source fields, run the generation commands from the checklist and targeted tests for the new source.

## Common pitfalls

- Source not visible in wizard: source not registered/imported, or schema not rebuilt.
- Generated config class still empty: forgot `generate:source-configs` after updating fields.
- Incremental sync misbehaving: wrong field name/type or wrong sort assumptions.
- Endless retries for bad credentials: missing `get_non_retryable_errors`.
- Dependent resource path `KeyError`: pre-format static path placeholders (see Fan-out).
- Silent truncation risk: page caps hit without logs/metrics.
- Drift from refactors: unused function params/helpers left behind after endpoint behavior changes.
- Type drift in endpoint config dicts: use source typing aliases (`Endpoint`, `ClientConfig`, `IncrementalConfig`) to keep static checks precise.
