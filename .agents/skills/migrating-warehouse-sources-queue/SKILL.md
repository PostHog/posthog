---
name: migrating-warehouse-sources-queue
description: >
  Moves the warehouse sources batch queue (sourcebatch, sourcebatchstatus, sourcegrouplease) to another queue with no downtime: a new Postgres database, or a new table set in the same database.
  Use when asked to migrate, move, re-home, re-partition or replace the warehouse sources queue or its database, to drain the old queue, to run loaders against two queues, or to finish or roll back such a migration.
  Covers the rollout order across this repo and the charts repo, the check that the old queue is empty, and the cleanup.
  Not for adding a column or an index to the queue tables (use django-migrations) and not for debugging a stuck sync.
---

# Migrating the warehouse sources queue

The mechanism is permanent code that is off by default.
Read "Migrating to another queue" in [products/warehouse_sources_queue/backend/README.md](../../../products/warehouse_sources_queue/backend/README.md) first: it defines a queue, the two settings, and the rules that keep one group from loading twice.
A migration needs no code change in this repo unless the new queue needs new migrations.
The work is configuration in the charts repo, done in the order below.

Every step that changes production needs the user's approval in the conversation.
Do not open a charts PR, change an environment variable, or scale a deployment on your own decision.

## Steps

```text
- [ ] 1. The new queue exists, has every migration, and has partitions
- [ ] 2. A build with the migration code is live on every loader
- [ ] 3. One charts change: flip the URLs and add the draining loaders
- [ ] 4. The draining queue is empty, and stays empty
- [ ] 5. One charts change: remove the draining URL and the draining loaders
- [ ] 6. The old queue is deleted
```

### 1. Prepare the new queue

- **Another database:** create it, then apply the `warehouse_sources_queue` product migrations to it. Use `/django-migrations` for how product database migrations run.
- **Other tables in the same database:** create a Postgres schema and a role whose `search_path` names it with `ALTER ROLE ... SET search_path`. Apply the migrations as that role, so the tables and `django_migrations` land in the new schema.
- Create the daily partitions for the next 7 days before any batch arrives. The partition workflow creates them only for the active queue, and the new queue is not active yet.
- The loader, producer and owner roles need the same grants as on the old queue.

Check: connect with the new URL and confirm that `sourcebatch`, `sourcebatchstatus` and `sourcegrouplease` exist and that `sourcebatch` has a partition for today.

### 2. Confirm the build on every loader

Do this before the flip, and do not combine it with the flip.
A loader that runs a build without the migration code reads only `WAREHOUSE_SOURCES_DATABASE_URL`.
After the flip that URL is the new queue, so such a loader consumes the new queue and takes no lease in the old one.
A `(team_id, schema_id)` group can then load from both queues at once.
Nothing in the code stops this, so the check is yours.

- Every loader deployment runs an image that contains `core/queue_migration.py`. Include each fleet split by `--claim-sync-types`.
- No pod of an older image remains: the rollout of that image has finished, and no rollback to an older image is in progress.
- Do not roll the loaders back to an older image while the draining URL is set. Finish or roll back the migration first.

Check: every loader pod logs `warehouse_sources_load_starting` with the fields `queue` and `holds_draining_queue_leases`.
A pod whose start line lacks those fields runs an older build.

The Temporal workers and the web and Celery pods need the same build before the flip.
An older build there is less severe: it reads and writes one queue only, so a supersede, a teardown or a takeover can miss batches in the other queue, and the stale-run sweeps correct that later.

### 3. Flip

Make one charts change that does all of this:

- Set `WAREHOUSE_SOURCES_DRAINING_DATABASE_URL` to the old queue's URL, and point `WAREHOUSE_SOURCES_DATABASE_URL` (and the `PRODUCT_DB_WAREHOUSE_SOURCES_QUEUE_*` variables, and `WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL`) at the new queue.
- Set both URL variables on every workload that reads the queue: the loaders, the Temporal workers that run data imports and CDC, and the web and Celery pods, which run teardown and the finalize sweep.
- Add a loader deployment that runs `run_warehouse_sources_load --queue draining`. Size it like the existing fleet. If the fleet is split by `--claim-sync-types`, either add one draining deployment per split or run one draining deployment with no sync-type filter.

The pods do not need to pick up the new configuration together, because step 2 put the same build on all of them.
During the rollout a pod with the old configuration reads and writes the old queue only, which the new loaders respect.
New batches wait in the new queue until the first active loader starts, so the cost of a slow rollout is delay.

Check after the rollout:

```bash
python manage.py manage_warehouse_queue migration-status
```

Both queues answer, and the active queue's `last_insert` moves.
The loader logs show `holds_draining_queue_leases=True` on the active fleet and `queue=draining` on the draining fleet.
`groups_held_for_draining_queue` log lines are expected: they are groups that wait for their old batches.

### 4. Wait until the old queue is empty

`migration-status` prints `draining queue is empty: the migration can finish` when both numbers are zero:

- `live_batches`: batches that wait or load.
- `open_runs`: runs that inserted in the last 24 hours and have no final batch. Their producers stay on the old queue until the run ends, so they can still insert.

Wait for that line on two checks at least one hour apart, with `last_insert` not moving between them.
An extraction activity can hold one run open for days.
If `open_runs` stays above zero, find the runs with `manage_warehouse_queue --queue draining status` and decide with the user whether to wait or to fail them with `manage_warehouse_queue --queue draining fail-run`.
A failed run keeps its committed cursor, so the next sync reads those rows again.

Do not leave the migration open for more than 7 days.
The old queue gets no new partitions and no retention after the flip.

### 5. Finish

Make one charts change that removes `WAREHOUSE_SOURCES_DRAINING_DATABASE_URL` everywhere and deletes the draining loader deployment.
A batch that still reaches the old queue after this change is never loaded.
Its job fails through the stale-run takeover and the next sync reads the rows again, so the cost is a delay, not lost data.

Check: `migration-status` prints that no migration is running, and the loader logs show `holds_draining_queue_leases=False`.

### 6. Clean up

Keep the old queue for a few days as evidence, then delete it with the user's approval.
The scheduler state and the generic job tables are not copied.
Nothing reads them for decisions while the scheduler runs in shadow mode.
Confirm that this is still true in the README's "Scheduler state" section before deleting the old queue.

## Rolling back

Before step 5, swap the two URLs: the new queue becomes the draining one and the old queue becomes active again.
The same rules then drain the new queue into nothing.
Move the `--queue draining` deployment along with the swap, because it must always consume the queue named by the draining URL.

## When something is wrong

- **The active loaders claim nothing.** They fail closed when they cannot reach the draining queue. Look for `draining_queue_lease_claim_failed`. Fix the connection, or finish the migration if the old queue is gone for good.
- **A group never loads from the new queue.** The old queue still has a batch of that group to load. `manage_warehouse_queue --queue draining status --team-id <id> --schema-id <id>` shows it. Check that the draining loaders run and claim that sync type.
- **A code change touches a queue call site.** New code that reads or writes the queue by job or by schema must use `all_queue_urls()`. Code that runs for a claimed batch uses `consuming_queue_url()`. A new producer uses `queue_url_for_run()`. All three are in `pipeline_v3/postgres_queue/queues.py`.
