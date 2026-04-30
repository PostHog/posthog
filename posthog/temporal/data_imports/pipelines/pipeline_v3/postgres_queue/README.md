# Postgres queue for warehouse batch loading

## Problem statement

The Kafka-based consumer for warehouse sources load worked but was fragile. Because a single load could run long, we had to keep pushing max.poll.interval.ms higher (along with session timeouts and max.poll.records) just to stop the broker from evicting consumers mid-batch, every increase was a bandaid, not a fix. On top of that, most of the real logic lived outside the message: retry state in Redis, DLQ routing through a second producer, schema-level locks and progress tracking in yet another store. The message itself was barely more than a pointer; Kafka was carrying the notification while everything that actually mattered happened elsewhere. Every configuration knob we added was compensating for a mismatch between what Kafka gives you and what we actually need.

## RudderStack's approach

RudderStack has been running warehouse loading on Postgres queues for 6+ years, handling 100K events/second at peak.
Their design uses two tables per queue (a jobs table and an append-only status table) which avoids UPDATE contention and keeps the write path insert-only.
They partition jobs into datasets of ~100K rows each, use COPY for bulk inserts, and run a compaction process to consolidate completed datasets.

You can find more on:

- [Why RudderStack Used Postgres Over Kafka](https://www.rudderstack.com/blog/why-rudderstack-used-postgres-over-apache-kafka-for-streaming-engine/)
- [Kafka vs PostgreSQL: Implementing Our Queueing System](https://www.rudderstack.com/blog/kafka-vs-postgresql-implementing-our-queueing-system-using-postgresql/)
- [Scaling Postgres Queues to 100K Events](https://www.rudderstack.com/blog/scaling-postgres-queue/)

## Our solution

We took RudderStack's two-table model (jobs + append-only status) but kept things simpler (for now, at least)

### What we use

- **Two tables**: `sourcebatch` (the jobs) and `sourcebatchstatus` (append-only status log). A `DISTINCT ON` view (`v_latest_source_batch_status`) gives us the latest status per batch.
- **Advisory locks** for cross-pod coordination: `pg_try_advisory_lock(namespace, hashtext(team_id:schema_id))` ensures no two pods process the same (team_id, schema_id) simultaneously. Session-level locks held for the duration of group processing, released explicitly after.
- **Async consumer** (`consumer.py`): single asyncio process that polls, groups batches by (team_id, schema_id), processes groups concurrently via `asyncio.gather`, batches within a group sequentially.
- **Recovery sweep**: periodic check (every 30s) for batches stuck in `executing` whose advisory lock is not held, those were owned by a crashed pod. Uses a separate connection so it doesn't interfere with the main lock session.
- **Sync producer** (`producer.py`): runs inside Temporal activities, plain `psycopg.Connection` with autocommit. Each `send_batch_notification` is a single INSERT.
- **New DB**: we created a new DB to store these two new tables

- **Daily range partitioning** on `created_at`: both tables use `PARTITION BY RANGE (created_at)` with daily partitions. Composite PK `(id, created_at)` is required by Postgres for partitioned tables. A DEFAULT partition catches rows that miss a partition. A Temporal scheduled workflow (`warehouse-sources-queue-partition-management`) runs every 6 hours to create the next 7 days of partitions and drop partitions older than 7 days. `DROP TABLE partition` is O(1) metadata-only — no vacuum, no dead tuples.
- **MATERIALIZED CTE for advisory locks**: `pg_try_advisory_lock` in a WHERE clause with LIMIT can acquire phantom locks on rows later discarded. All consumer queries use a MATERIALIZED CTE to fully resolve candidates before probing locks.
- **Partition pruning bounds**: all consumer queries include `created_at > now() - interval '14 days'` (2x the 7-day retention) so the planner can skip dropped partitions.

### What we left out

- **COPY bulk inserts**: the producer inserts one row per batch. At our volume, row-level INSERT is fine. (We can always move to bulk insert if needed)
- **Compaction**: RudderStack runs a background process to merge/drop completed datasets, it stores tables up to 100k rows and then they roll to the next one. We don't need it at the moment, but if we end up implementing rolling datasets, we will implement this compaction too.
- **Caching layers**: RudderStack uses "no jobs" caches and active pipeline caches to reduce query load. Our poll query is cheap enough with proper indexing.
- **Recursive CTE loose index scans**: their trick for finding distinct pipeline IDs efficiently. Our `get_unprocessed_and_lock` query is simple enough without it.
- **Active Partitions**: RudderStack designs a partition and then it assigns each partition to one processor instance, this is similar to how Kafka partitions work. We don't need this, this will be an overkill as we don't have any specifics for a partition.

### Architecture

![Postgres queue architecture](./20260423%20-%20PostgresArchitecture.png)

## Things to look out for during roll out

- **Partition health**: monitor that the `warehouse-sources-queue-partition-management` Temporal schedule is running. Alert on rows landing in DEFAULT partitions (means partition creation failed).
- **DB Load**: we will keep an eye on the load and the locks to make sure the tables can hold the full load of warehouse sources

## Extra. Paths (CLAUDE GENERATED)

All state transitions are **inserts** into `sourcebatch`; rows in `sourcebatch` are never updated.
The latest state per batch comes from the view `v_latest_source_batch_status` (`DISTINCT ON (batch_id) ... ORDER BY batch_id ASC, id DESC`).
The consumer uses an **autocommit** connection, a **session-level** `pg_try_advisory_lock(ns, hashtext("team_id:schema_id"))`, and polls every ~2s for up to `poll_limit` pending batches via `get_unprocessed_and_lock`.

### Happy path

```text
t=0   Producer (Temporal activity, autocommit):
        INSERT batch 1 (run=R, team=T, schema=S, batch_index=1)
        INSERT batch 2 (run=R, team=T, schema=S, batch_index=2)
      No status rows yet -> the view reports these as unprocessed.

t=1   Consumer A poll tick (get_unprocessed_and_lock):
        SELECT ... FROM batch b
        LEFT JOIN v_last_external_data_job_batch_status s ON b.id = s.batch_id
        WHERE (s.batch_id IS NULL OR s.job_state = 'waiting_retry')
          AND b.run_uuid NOT IN (<runs with any failed batch>)
          AND pg_try_advisory_lock(ns, hashtext(b.team_id || ':' || b.schema_id))
        ORDER BY b.id ASC LIMIT N;
      -> returns batches 1 and 2; advisory lock for (T,S) is held on this session.

t=2   _group_by_key groups results by (team_id, schema_id):
        groups[(T,S)] = [batch 1, batch 2]
      asyncio.gather runs each group via _process_group; batches within
      a group are awaited sequentially.

t=3   _process_single(batch 1):
        INSERT status(batch=1, job_state='executing', attempt=1)  -- pre-increment
        await process_batch(batch 1)  -- loads parquet into Delta Lake
        INSERT status(batch=1, job_state='succeeded', attempt=1)

t=4   _process_single(batch 2):  same sequence, attempt=1 -> succeeded.

t=5   End of _process_group (finally):
        SELECT pg_advisory_unlock(ns, hashtext('T:S'))
      (Also released at shutdown via pg_advisory_unlock_all.)

t=6   Producer inserted batches 3, 4 in the meantime.
      They are picked up on a later poll tick -- by this pod or another.
      The advisory lock arbitrates which pod drains the group at any
      given moment; there is no inner loop that picks up new work
      mid-group.
```

### Transient failure + retry

```text
tX    _process_single(batch K):
        INSERT status(K, 'executing', attempt=1)
        await process_batch(K)  -- raises (e.g. S3 read timeout)
      Caught in _process_single:
        if attempt >= max_attempts (3) -> _fail_run
        else -> INSERT status(K, 'waiting_retry', attempt=1, error_response={...})

tX+1  Next poll: batch K matches (s.job_state = 'waiting_retry'), lock still
      acquirable -> returned again. _process_single runs with
      attempt = latest_attempt + 1 = 2.
```

### Max retries exceeded

```text
      _process_single on the final attempt raises -> _fail_run(batch, reason):
        fail_run(conn, run_uuid) issues a single INSERT ... SELECT that
        appends a 'failed' status for every batch in the run whose current
        state is NULL / waiting / waiting_retry / executing.
        _update_job_status_to_failed marks the ExternalDataJob as FAILED
        via the Django ORM (sync_to_async).
      Subsequent polls skip the whole run via the
      NOT IN (<runs with any failed batch>) filter.
```

### OOM / pod crash mid-batch (recovery sweep)

```text
t=0   _process_single(batch K):
        INSERT status(K, 'executing', attempt=k)  -- commits (autocommit)
        load starts

t=1   OS OOM-killer SIGKILLs the pod.
      Postgres detects the connection drop and auto-releases the
      session-level advisory lock. Latest state of K stays 'executing'
      in the view -- that row is durable.

t=2   Every 30s, _recovery_loop on some consumer runs _recovery_sweep
      against its dedicated _recovery_conn:
        SELECT b.*, COALESCE(s.attempt, 0) FROM batch b
        JOIN v_last_external_data_job_batch_status s ON ...
        WHERE s.job_state = 'executing'
          AND pg_try_advisory_lock(ns, hashtext(b.team_id || ':' || b.schema_id))
        ORDER BY b.id ASC;
      Only orphans pass the filter -- if another pod is still processing
      (T,S), pg_try_advisory_lock returns false. Each returned row's
      probe lock is immediately released with pg_advisory_unlock.

t=3   For every orphan:
        if latest_attempt >= max_attempts -> _fail_run
                                             (reason: "max retries exceeded (likely OOM)")
        else -> INSERT status(K, 'waiting_retry', attempt=latest_attempt)
      No +1: the 'executing' insert at t=0 already consumed an attempt.

t=4   On the next main poll, batch K is picked up via the
      'waiting_retry' branch and retried (attempt becomes
      latest_attempt + 1 on re-execute).
```

### Graceful shutdown (SIGTERM / SIGINT)

```text
      Signal handler sets self._shutdown.
      Main loop checks _shutdown.is_set() and exits after the current
      asyncio.gather completes. Inside _process_group, the per-batch
      loop also checks _shutdown and breaks early, leaving remaining
      batches in the group for the next consumer (their state is
      still 'waiting' -- no 'executing' row was written).
      _close cancels the recovery task, runs pg_advisory_unlock_all
      on the main connection, and closes both connections.
```
