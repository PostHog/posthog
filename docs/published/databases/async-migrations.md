---
title: How to write an async migration
sidebar: Handbook
showTitle: true
---

Also see: user-facing documentation under [in the runbook](/docs/runbook/async-migrations)

### Writing an async migration

To write an async migration, you should create a migration file inside [`posthog/async_migrations/migrations`](https://github.com/PostHog/posthog/tree/master/posthog/async_migrations/migrations). The name should follow the convention we use for Django and EE migrations (e.g. `0005_update_events_schema`). Check out the existing migrations or [examples](https://github.com/PostHog/posthog/tree/master/posthog/async_migrations/examples).

### Workflow and architecture

#### Setup

When the Django server boots up - a setup step for async migrations happens, which does the following:

1. Imports all the migration definitions
2. Populates a dependencies map and in-memory record of migration definitions
3. Creates a database record for each
4. Check if all async migrations necessary for this PostHog version have completed (else don't start)
5. Triggers migrations to run (in order) if `AUTO_START_ASYNC_MIGRATIONS` is set and there are uncompleted migrations for this version

#### Running a migration

When a migration is triggered, the following happens:

1. A task is dispatched to Celery to run this migration in the background
2. The following basic checks are performed to ensure the migration can indeed run:
    1. We're not over the concurrent migrations limit
    2. The migration can be run with the current PostHog version
    3. The migration is not already running
    4. The service version requirements are met (e.g. X < ClickHouse version < Y)
    5. The migration's `is_required` check passes
    6. The migration's `healthcheck` passes
    7. The migration's dependency (if any) has been completed
3. We run through each of the operations in order
4. Every 30 minutes, a Celery task performs a healthcheck, to ensure that:
    1. The Celery process running the migration didn't crash
    2. The migration's healthcheck still passes

> **Note:** Async migrations can also be run synchronously (i.e. not in Celery) using the async migrations CLI (WIP) or the Django shell.

#### Stopping a migration

A migration can be stopped from the async migrations management page or by issuing a command via Celery's app control to terminate the process running the task.

#### Rollbacks

If a migration is stopped for any reason (manual trigger or error), we will attempt to roll back the migration following the operations specified in reverse order from the last started operation.

If a roll back succeeds, the migration status will be updated to reflect this.

#### Errors

If a migration errors, the error message is added to the migration's database record and we automatically trigger a rollback.

### Scope and limitations

The initial implementation of async migrations targets only **data migrations**, and assumes that the migration is used as a mechanism to help users move into a new default state.

For example, when we [moved our ClickHouse `person_distinct_id` table to a `CollapsingMergeTree`](https://github.com/PostHog/posthog/pull/5563), we updated the SQL for creating the table, and wrote a migration to help users on the old schema migrate to the new schema.

However, users that did a fresh deploy of PostHog _after_ this change already had the table with the new schema created by default.

This is the only type of operation that async migrations _currently_ support, to prevent a complex web of dependencies between migration types.

As such, those writing an async migration should write a sensible `is_required` function that determines if the migration should run or not.

Thus, when a user deploys a new PostHog instance, we will first run **all** EE migrations in order, and then **all** of the async migrations in order. At this step, async migrations should be skipped if the codebase already contains updated default schemas.

For instance, here's a good `is_required` function, which ensures the migration will only run if the table does not already exist.

```python
def is_required(self):
    result = sync_execute("SELECT count(*) FROM system.tables WHERE database='posthog' AND name='table_x_new'")
    return result[0][0] == 0
```

Is required functions could also take into consideration table schemas, for example by checking the output of `SHOW CREATE TABLE` in ClickHouse.

### Codebase structure

The codebase is structured as follows:

#### posthog/models/async_migration.py

The Django ORM (Postgres) model for storing metadata about async migrations.

#### posthog/api/async_migrations.py

API for requesting data about async migrations as well as triggering starts, stops, and rollbacks.

#### posthog/tasks/async_migrations.py

Celery tasks for dealing with async migrations. These are:

1. `run_async_migration`: Explicitly triggered to run a migration
2. `check_async_migration_health`: Runs every 30 minutes to perform a healthcheck

#### posthog/async_migrations/definition.py

Classes to be used when writing an async migration, outlining the necessary components of a migration.

#### posthog/async_migrations/setup.py

Code that runs when the Django server boots to setup the necessary scaffolding for async migrations.

#### posthog/async_migrations/runner.py

Code related to running an async migration, from executing operations in sequence to attempting rollbacks.

#### posthog/async_migrations/utils.py

Code to support the runner in tasks that do not depend on the availability of the migration definition (module).
