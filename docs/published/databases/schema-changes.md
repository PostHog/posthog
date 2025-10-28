---
title: Making schema changes safely
sidebar: Handbook
showTitle: true
---

PostHog's database schema evolves constantly along with the app.
Each schema change safely requires delibration though, as a badly designed migration can cause pain for users,
and require extra effort from the engineering team.

Below are some important considerations to keep in mind regarding schema changes:

## General considerations

Before making a schema change, consider:
- Do we need the schema change at all? Would this be better solved with an application-level code change instead?
- Is my change backwards compatible? Both old and new code _will_ be running in parallel in both posthog cloud and self-hosted, so breaking changes can and will cause outages.
- Can I deploy my schema change separately from application code change? For non-trivial changes, you want to deploy schema change first to ensure it's easy to roll back and if it's backwards compatible.
- Am I doing a blocking migration? Migrations which lock huge tables can easily cause outages.

If you're doing anything tricky, it is worth reading up on zero-downtime migrations and make sure you know how the change will work operationally in practice.

## Do not delete or rename Django models and fields

Deleting and renaming tables and columns, even completely unused ones, is strongly discouraged.

The reason is that the Django ORM **always** specifies tables and columns to fetch in its `SELECT` queries – so when a migration moves a table/column away, in between the migration having ran and the new server having deployed completely, there's a period where the old server is still live and tries to `SELECT` that column. The only thing it gets from the database though is an error, as the resource isn't there anymore! This situation results in a period of short-lived but very significant pain for users.

To avoid this pain, **AVOID deleting/renaming models and fields**. Instead:
- if the name is no longer relevant, keep it the same in the database – feel free to change the naming in Python/JS code, but make sure the change ISN'T reflected in the database,
- if the field itself is no longer relevant, just clearly mark it with a `# DEPRECATED` comment in code
- make the field not be queried by overriding `get_queryset` in a Manager object. See [this PR](https://github.com/PostHog/posthog/pull/13512) for an example.

## Design for scale

With any migration, make sure that it can run smoothly not only in local development, but also on self-hosted instances, and on PostHog Cloud.

Generally this means avoiding migrations that need to process each row individually on _large_ tables (events, but also persons, person distinct IDs, or logs), as then the migration may take forever, or may even obtain a persisting lock on the entire table, causing severe issues for the app.

Examples of operations dangerous at scale are:
- Adding new fields **with a non-null default** (null is fine, as it avoids a lock).
- Iterating over all rows individually.
- Adding an index

> For a quick overview of what Cloud scale _looks like_, see [Vanity Metrics in Metabase](https://metabase.posthog.net/dashboard/1).

## Tread carefully with ClickHouse schema changes

ClickHouse is at the core of PostHog's scalable analytics capabilities. The ClickHouse schema can be changed just like the Postgres one – with migrations – but there are two important bits of complexity added:

1. ClickHouse has no indexes like traditional databases. Instead, each table has a sorting key, defined in the `ORDER BY` clause of the table. This determines how data is laid out on disk, and ClickHouse reads data in the order it's laid out, so it's important that the sorting key is optimal for the table's use cases.
2. Tables that store events are _sharded_ + _distributed_ in PostHog Cloud. This improves performance in multi-tenant architecture, but means that updating these is not straightforward like with most tables, and may require manual write access to the cluster.

To make sure that your new ClickHouse migration is A-OK – both above points having been addressed – make sure you loop in someone with extensive experience operating ClickHouse for review. Ask for feedback in the `#team-clickhouse` Slack channel.
