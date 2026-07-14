---
name: analyzing-insights-across-teams
description: >
  Analyze PostHog insights, dashboards, or teams beyond the current project by
  querying the prod Postgres replicas synced into the dogfood data warehouse
  (US project 2, "PostHog App + Website"). Use when asked to analyze insights
  across all teams or projects, another team's insights, or fleet-wide
  insight/dashboard usage — cases where `system.insights` only returns the
  current project's rows and the agent would otherwise report the data as
  inaccessible. Covers the synced table names for US and EU and the
  column-verification workflow.
---

# Analyzing insights across teams

`system.*` entity tables (e.g. `system.insights`) are scoped to the current project,
and the generic `execute-sql` guidance says other teams' data is inaccessible.
For the dogfood project (US project 2) that is not the whole story:
production Postgres tables are replicated into the project's data warehouse,
so cross-team entity metadata **is** queryable with `posthog:execute-sql`.
Do not stop at `system.insights` when the question spans teams.

## Synced tables

| Entity           | US (prod-us)                     | EU (prod-eu)                        |
| ---------------- | -------------------------------- | ----------------------------------- |
| Insights         | `postgres.posthog_dashboarditem` | `eu_postgres_posthog_dashboarditem` |
| Dashboards       | `postgres.posthog_dashboard`     | `eu_postgres_posthog_dashboard`     |
| Teams / projects | `postgres.posthog_team`          | `eu_postgres_posthog_team`          |

- Underscore aliases (e.g. `postgres_posthog_dashboarditem`) point at the same synced data.
- These are replicas of the Django tables in this repo (`posthog_dashboarditem` backs the `Insight` model), so rows span every team; `team_id` is the scoping column.
- More prod tables than these are synced. Before concluding cross-team data is inaccessible, check the catalog:

  ```sql
  SELECT table_name, description
  FROM system.information_schema.tables
  WHERE table_type = 'data_warehouse' AND table_name ILIKE '%postgres%'
  ```

## Workflow

1. Confirm columns before projecting — synced schemas drift with the Django models:

   ```sql
   SELECT column_name, data_type
   FROM system.information_schema.columns
   WHERE table_name = 'postgres.posthog_dashboarditem'
   ```

2. Query with `posthog:execute-sql`, filtering or grouping by `team_id`. Join `postgres.posthog_team` for team names. Example — most active teams by insights created in the last 30 days:

   ```sql
   SELECT i.team_id, any(t.name) AS team_name, count() AS insights_created
   FROM postgres.posthog_dashboarditem AS i
   LEFT JOIN postgres.posthog_team AS t ON t.id = i.team_id
   WHERE NOT i.deleted AND i.saved AND i.created_at >= now() - INTERVAL 30 DAY
   GROUP BY i.team_id
   ORDER BY insights_created DESC
   LIMIT 20
   ```

3. Remember the sync lag: these are periodic replicas, not live reads — fine for analysis, not for "right now" state.

## Caveats

- Query results may contain customer team names and metadata — keep them out of public surfaces (PR descriptions, commit messages, uploaded screenshots).
- For cross-team **event/analytics** data (not entity metadata), see the `query-clickhouse-via-metabase` skill instead.
