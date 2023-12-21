---
title: Async Migrations
---

How to write async migrations: https://posthog.com/handbook/engineering/databases/async-migrations

## What are async migrations?

Async migrations are _data migrations_ that do not run synchronously on an update to a PostHog instance. Rather, they execute on the background of a running PostHog instance, and should be completed within a range of PostHog versions.

You can check the PostHog blog for more [information about how and why we enable async migrations on PostHog](/blog/async-migrations).

Further internal information about async migrations can be found in [our handbook](/handbook/engineering/databases/async-migrations).

## Why are async migrations necessary?

Migrations are inevitable, and sometimes it may be necessary to execute non-trivial schema changes that can take a long time to complete.

For example, ClickHouse does not support changing the primary key of a table, which is a change we were [forced to make in anticipation of upgrading ClickHouse beyond version 21.6](https://github.com/PostHog/posthog/issues/5684). As a result, the way to change the schema of the table was to create a new table and insert all the data from the old table into it, which took us an entire week to run on PostHog Cloud.

Now, while we at PostHog can execute such changes to our Cloud instance "manually", we felt compelled to provide a better approach for our users to do so.

As a result, we created a system capable of safely and efficiently managing migrations that need to happen asynchronously.

## Working with async migrations

Managing async migrations is a job for self-hosted PostHog instance admins. These migrations require some level of supervision as they affect how data is stored and may run for long periods of time.

However, worry not! We've built a system to make managing these as easy as possible.

### Prerequisite

Make sure you're on PostHog App version 1.33 or later.

To manage async migrations, you must be a staff user. PostHog deployments from version 1.31.0 onwards will automatically give the instance's first user "staff status", but those who have deployed PostHog before 1.31.0 will have to manually update Postgres.

To do so, follow our [guide for connecting to Postgres](/docs/self-host/deploy/troubleshooting#how-do-i-connect-to-postgres) and then run the following query:

```sql
UPDATE posthog_user
SET is_staff=true
WHERE email=<your_email_here>
```

To confirm that everything worked as expected, visit `/instance/async_migrations` in your instance. If you're able to see the migrations info, you're good to go!

### Async migrations page

We've added a page where you can manage async migrations at `/instance/async_migrations`.

On this page you can trigger runs, stop running migrations, perform migration rollbacks, check errors, and gather useful debugging information.

Here's a quick summary of the different columns you see on the async migrations table:

| Column | Description |
| :----- | :-------- |
| Name and Description | The migration's name. This corresponds to the migration file name in [`posthog/async_migrations/migrations`](https://github.com/PostHog/posthog/tree/master/posthog/async_migrations/migrations) followed by an overview of what this migration does |
| Status | The current [status](https://github.com/PostHog/posthog/blob/master/posthog/models/async_migration.py#L5) of this migration. One of: 'Not started','Running','Completed successfully','Errored','Rolled back','Starting'. |
| Progress | How far along this migration is (0-100) |
| Current operation index | The index of the operation currently being executed. Useful for cross-referencing with the migration file |
| Current query ID | The ID of the last query ran (or currently running). Useful for checking and/or killing queries in the database if necessary. |
| Started at | When the migration started. |
| Finished at | When the migration ended. |

The settings tab allows you to change the configuration, e.g. whether async migrations should run automatically.

### How can I stop the migration?

In the async migrations page at `/instance/async_migrations` you can choose to `stop` or `stop and rollback` the migration from the `...` button on the right most column.

![Stopping the migration](./async-migrations-stop-rollback.png)

### The migration is in an Error state - what should I do?

Try to rollback the migration to make sure we're in a safe state. You can do so from the async migrations page at `/instance/async_migrations` from `...` button on the right most column. If you're unable to rollback [reach out to us](https://app.posthog.com/home#supportModal).

![Rollback errored migration](./async-migrations-error-rollback-button.png)


### Celery scaling considerations

To run async migrations, we occupy one Celery worker process to run the task. Celery runs `n` processes (per pod) where `n == number of CPU cores on the posthog-worker pod`. As such, we recommend scaling the `posthog-worker` pod in anticipation of running an async migration.

You can scale in two ways:

1. Horizontally by increasing the desired number of replicas of `posthog-worker`
2. Vertically by increasing the CPU request of a `posthog-worker` pod

Once the migration has run, you can scale the pod back down.

### Error Upgrading: Async migrations are not completed

You might have ran into a message like this:
```
List of async migrations to be applied:
- 0123_migration_name_1 - Available on Posthog versions 1.35.0 - 1.40.9
- 0124_migration_name_2 - Available on Posthog versions 1.37.0 - 1.40.9
Async migrations are not completed. See more info https://posthog.com/docs/self-host/configure/async-migrations/overview
```

This means you were trying to update to a version that requires these async migrations to be completed.
1. If you're on a version that has these migrations available you can head over to the async migrations page (at `/instance/async_migrations`). After completing the required migrations, re-run the upgrade. Note: we recommend a minimum version of 1.33.0 for running async migrations for a smoother experience.
1. If you're not on a version that has the migration available you'll first need to upgrade to that version. Then head over to the async migrations page (at `/instance/async_migrations`). After completing the required migrations you can continue upgrading forward.

The table below lists out recommended PostHog app and chart versions to use for updating to if there's a need for a multi step upgrade.

| Async Migration | PostHog Version | Chart Version | Notes  |
| --------------- | --------------- | --------------| ------ |
| 0001            | 1.33.0          | 16.1.0        |        |
| 0002            | 1.33.0          | 16.1.0        |        |
| 0003            | 1.33.0          | 16.1.0        |        |
| 0004            | 1.36.1          | 26.0.0        | This NOT the default PostHog version for v26 Chart version, see upgrade instructions below. Run the async migration right after upgrading as there could be problems with ingestion otherwise | 
| 0005            | 1.41.4          | 29.0.11       |        |
| 0006            | 1.41.4          | 29.0.11       |        |
| 0007            | 1.41.4          | 29.0.11       | Completing this migration enables person on events. Further information: https://posthog.com/blog/persons-on-events |

#### Upgrading helm chart to a specific version

To upgrade to a specific PostHog app version specify the desired version in your `values.yaml`
```
image:
  tag: release-1.36.1
```

To upgrade to a specific chart version you can use `--version <desired version>` flag, e.g.
```
helm upgrade -f values.yaml --timeout 30m --namespace posthog posthog posthog/posthog --atomic --wait --wait-for-jobs --debug --version 16.1.0
```
Make sure you have followed the [upgrade instructions](https://posthog.com/docs/runbook/upgrading-posthog) for your platform (specifically major upgrade notes as needed).

### Error Upgrading: Async migration is currently running 

If your pods are crashlooping and you just want the app to be up the fastest way possible, then mark the running migration as error state in Postgres. You'll likely want to follow-up to rollback the async migration in the UI as soon as possible to clear the state and then plan for upgrading.

## Customer support

Async migrations completion requirements are called out in [upgrade notes](../upgrade-notes).

If upgrading from a really old version use chart and PostHog version recommendations from this table (other version combinations may run into various problems): https://posthog.com/docs/runbook/async-migrations#error-upgrading-async-migrations-are-not-completed

If 0007 fails (this migration is necessary for PoE queries, but we're not planning to roll that to self-hosted users ever)
1. disable post-checks and disable PoE queries
2. run step 1 manually and then mark the migration as completed in postgres (but even step 1 can probably be ignored)
