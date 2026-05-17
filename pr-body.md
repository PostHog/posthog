## Summary

Adds support for discovering and syncing tables from multiple schemas in PostgreSQL databases.

## Changes

- **Backend** (`posthog/temporal/data_imports/sources/`):
  - Added `include_all_schemas: bool` field to `PostgresSourceConfig`
  - Added new `SourceFieldSwitchConfig` schema type for toggle UI
  - Updated `get_schemas()` to fetch all non-system schemas when flag is enabled
  - Updated validation to allow skipping schema when "include all schemas" is enabled

- **Frontend** (`products/data_warehouse/frontend/`):
  - Added switch type handling in `SourceForm.tsx` to render the toggle

## How it works

When users enable the "Include all schemas" toggle in the PostgreSQL source configuration, the backend passes `None` to the schema parameter, which fetches all non-system schemas (existing behavior). When disabled, it works as before with a single schema.

## Testing

To test:
1. Set up PostHog development environment
2. Navigate to Data Warehouse → Add Source → PostgreSQL
3. Enable "Include all schemas" toggle
4. Verify tables from multiple schemas are discovered

Closes #58643