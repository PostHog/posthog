QUERY_POSTGRES_CONTEXT_PROMPT = """You have access to query PostgreSQL tables containing PostHog configuration data.

Available tables:
- dashboard: User dashboards with name, description, pinned status
- insight: Saved insights with name, description, query configuration
- featureflag: Feature flags with key, name, active status, rollout percentage
- experiment: A/B experiments with name, description, metrics
- survey: User surveys with name, questions, targeting
- notebook: Notebooks with title and content
- action: Custom actions/events with name and configuration

Security: All queries are automatically filtered by team_id and user access permissions.
You cannot see data from other teams or data you don't have access to.

Use HogQL syntax (similar to SQL) for your queries."""


QUERY_POSTGRES_RECOVERABLE_ERROR_PROMPT = """The query failed with an error:

{error}

Please fix the query and try again. Common issues:
- Table or column name typos
- Invalid HogQL syntax
- Querying tables that don't exist"""


QUERY_POSTGRES_UNRECOVERABLE_ERROR_PROMPT = """The query failed with an unexpected error. Please try a simpler query or ask the user for more specific requirements."""
