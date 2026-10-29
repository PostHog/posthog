# Integrations SDK: rules for callers

Read `README.md` before you change the SDK or add an operation.

- Read and write `Integration` rows only through `IntegrationManager` from `posthog.integrations`. Never import the `Integration` model, its managers or its relations. The semgrep ratchet `integration-model-through-sdk` fails CI on new uses.
- Pick the accessor by kind and auth type: `IntegrationManager.<kind>.<oauth|token|credentials>` for code that reads one config shape. Use `.any` or `IntegrationManager.kinds(...)` only for code that handles every auth type the same way, such as a picker or a delete.
- Rows are read-only `IntegrationRecord`s. Do not call `.save()`, `.delete()` or `.refresh_from_db()` on a row, and do not write to `row.config`. Write with `update` or `upsert`, and delete with `delete`.
- Do not read related rows (`row.team`, `row.created_by`). Use `row.team_id` and `row.created_by_id`. Set a foreign key with its id column (`integration_id=row.id`).
- Warehouse source rows (`config["warehouse_source_type"]`) are hidden by default. Add `.with_source_rows()` only in code that handles every row the same way, such as the integrations list and delete API. Use `IntegrationManager.source(kind)` for the source credentials themselves.
- Refresh an OAuth token with `IntegrationManager.<kind>.oauth.refresh_access_token(team_id, id, stale_access_token=...)`. Do not lock a row yourself.
- When an operation is missing, add a small named operation to the SDK. Do not widen `find(where=...)`, which compares named config keys for equality only, and never return a queryset.
- The model moves behind an HTTP API in the credentials service. Every operation must work over that transport: no callbacks into caller code inside a transaction, no querysets, no model instances that callers write.
- When you move a file to the SDK, lower its count in `model_access_baseline.txt`, or remove the line at zero.
