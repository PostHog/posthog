READ_DATA_BILLING_PROMPT = """
# Billing information

Use this tool with the "billing_info" kind to retrieve the billing information if the user asks about their billing, subscription, product usage, spending, or cost reduction strategies.
You can use the information retrieved to check which PostHog products and add-ons the user has activated, how much they are spending, their usage history across all products in the last 30 days, as well as trials, spending limits, billing period, and more.
If the user wants to reduce their spending, always call this tool to get suggestions on how to do so.
If an insight shows zero data, it could mean either the query is looking at the wrong data or there was a temporary data collection issue. You can investigate potential dips in usage/captured data using the billing tool.
""".strip()

READ_DATA_PROMPT = """
Use this tool to read user data created in PostHog. This tool returns data that the user manually creates in PostHog.

This tool should be used for direct retrieval (by ID, name, etc.). Use the search tool instead for finding entities by name, description. If the search tool doesn't return matching entities, try pagination instead using the list_data tool.

# Data warehouse schema

Read the SQL ClickHouse schema (tables, views, and columns) for the user's data.

## Available operations:
- `data_warehouse_schema`: Returns core PostHog tables (events, groups, persons, sessions) with their full schemas, plus a list of available data warehouse tables and views (names only). Use this first to see what data is available.
- `data_warehouse_table`: Returns the full schema for a specific data warehouse table or view. Use this after `data_warehouse_schema` to get details on specific tables you need.

You MUST use this tool when:
- Working with SQL.
- The request is about data warehouse, connected data sources, etc.

Workflow:
1. Start with `data_warehouse_schema` to see available tables
2. Use `data_warehouse_table` with a specific `table_name` to get schema details for warehouse tables you need

# Insight

Retrieves and optionally retrieves data for an existing insight by its ID.

## Use this when:
- You have an insight ID and want to retrieve the data for that insight or read the insight schema.
- The user wants to see or discuss a specific saved insight.
- You need to understand what an existing insight shows.

# Feature flag

Retrieves a feature flag by its numeric ID or key (slug).

## Use this when:
- You have a feature flag ID or key and want to retrieve its configuration.
- The user wants to see details about a specific feature flag.
- You need to understand what conditions and variants a feature flag has.

## Parameters:
- id: The numeric ID of the feature flag (optional if key is provided)
- key: The key/slug of the feature flag (optional if id is provided)

# Experiment

Retrieves an experiment by its numeric ID or by its feature flag's key.

## Use this when:
- You have an experiment ID or its feature flag key and want to retrieve its configuration.
- The user wants to see details about a specific A/B test experiment.
- You need to understand the experiment's variants, status, or conclusion.

## Parameters:
- id: The numeric ID of the experiment (optional if feature_flag_key is provided)
- feature_flag_key: The key of the experiment's feature flag (optional if id is provided)

{{{billing_prompt}}}
""".strip()

BILLING_INSUFFICIENT_ACCESS_PROMPT = """
The user does not have admin access to view detailed billing information. They would need to contact an organization admin for billing details.
Suggest the user to contact the admins.
""".strip()

INSIGHT_NOT_FOUND_PROMPT = """
The insight with the ID "{short_id}" was not found or uses an unsupported query type. Please verify the insight ID is correct.
""".strip()

DASHBOARD_NOT_FOUND_PROMPT = """
The dashboard with the ID "{dashboard_id}" was not found. Please verify the dashboard ID is correct.
""".strip()

READ_DATA_WAREHOUSE_SCHEMA_PROMPT = """
# Core PostHog tables
{{{posthog_tables}}}
{{#data_warehouse_tables}}

# Data warehouse tables
{{{data_warehouse_tables}}}
{{/data_warehouse_tables}}
{{#data_warehouse_views}}

# Data warehouse views
{{{data_warehouse_views}}}
{{/data_warehouse_views}}

<system_reminder>
Use the `read_data` tool with the `data_warehouse_table` kind to get column and relationship details for a specific table.
</system_reminder>
""".strip()
