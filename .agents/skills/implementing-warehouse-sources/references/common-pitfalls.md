# Common pitfalls

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
- Dependent resource path `KeyError`: pre-format static path placeholders (see fan-out in fetching-data.md).
- Silent truncation risk: page caps hit without logs/metrics.
- Drift from refactors: unused function params/helpers left behind after endpoint behavior changes.
- Type drift in endpoint config dicts: use source typing aliases (`Endpoint`, `ClientConfig`, `IncrementalConfig`) to keep static checks precise.
- Partition key instability: picked `updated_at` instead of `created_at`; partitions rewrite on every sync.
- Hardcoded Logo.dev key committed: always ask the user for the key at runtime.
