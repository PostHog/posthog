I've created a PR to implement this feature!

Here's what the implementation does:
- Added an "Include all schemas" toggle in the PostgreSQL source configuration
- When enabled, the backend discovers and syncs tables from ALL non-system schemas in the database (instead of just one)
- When disabled, works exactly as before with a single schema

**Changes made:**
- Backend: Added `include_all_schemas` field to PostgresSourceConfig + updated schema discovery logic
- Frontend: Added switch/toggle component for the new field

**PR:** https://github.com/PostHog/posthog/pull/58694

Looking forward to your feedback!