# Static cohort population and recovery

Static membership is written to ClickHouse first, then to Postgres through personhog. Feature flags
read Postgres membership. A failure between writes can leave the stores inconsistent; a failure
before later upload batches can also leave people absent from both stores.

## Durable population

For enabled teams, `cohort_population_operations` records the source, phase, checkpoint, retry
budget and retained input. The partial unique constraint reserves a cohort until its operation is
completed or abandoned. Failed operations remain unresolved.

Uploads persist normalized identifiers in private object storage before admission. Query and filter
operations persist their definition and checkpoint ClickHouse materialization before synchronization.
Feature flag operations pin definition versions and retain each fetched page before writing it.

Each Celery task runs one work unit: an input chunk, flag page, synchronization page, source
materialization or final count. Checkpoints require both membership writes to succeed. Expired
ownership tokens cannot advance progress or finalize an operation. Personhog serializes inserts per
cohort and deduplicates person IDs. The gRPC transport never retries `InsertCohortMembers`, because
`posthog_cohortpeople` has no unique index and a retry can overlap the attempt still running on a
replica; the runner replays the chunk after its backoff instead.

Six operation retries use exponential backoff with jitter, starting at 60 seconds and capped at
30 minutes. Final count and cohort bookkeeping retry independently of completed membership writes.
The dispatcher runs every two minutes to recover missed publishes, due retries and expired leases.
A publish made within the last five minutes is not repeated, so a backed-up queue does not collect
a duplicate delivery per pass.

ClickHouse-first writes preserve existing visibility semantics. Recovery does not make the two
stores atomically visible. A crash after ClickHouse materialization but before its checkpoint can
repeat materialization; a completed checkpoint is never reevaluated during Postgres recovery.

## Recovery actions

The project-scoped `retry_population` and `abandon_population` actions require `cohort:write`.
The read-only `population` response describes progress and available actions.

- **Retry** resumes saved progress with a fresh retry budget. Missing or expired input requires
  re-upload; a changed feature flag definition requires a new population.
- **Stop** waits for an active attempt to settle, synchronizes the already-written ClickHouse subset,
  counts it, and records an abandoned, incomplete outcome.
- Uploads, additions, removals and source changes return `409 population_in_progress` while a run
  remains unresolved. Names and descriptions remain editable.
- Synchronous additions return `success: true` only after completion. A dependency failure returns
  a typed error with the operation to follow.
- Creating a cohort with person IDs writes the first 50 chunks inline and hands the rest to a
  worker. The response is the created cohort with its `population`; a failed write is reported
  there, so a caller never has to create a second cohort to retry.

The UI polls current progress without overwriting unsaved metadata. Last successful import
statistics remain separate from the current run.

Retained failed input expires after **30 days**. Completed or abandoned input is scheduled for
deletion within **24 hours**, with cleanup on the next dispatcher sweep. Cleanup includes
uncheckpointed flag pages and retries partial storage deletions. Configure a bucket lifecycle for
the private `cohort_population/` prefix to bound orphan retention if an upload process dies before
creating its operation row; account for active operations and the failed-input retention window.

## Historical audit and targeted repair

Store consistency and original import completeness are separate findings. The audit resolves
ClickHouse UUIDs through personhog, skips deleted or unresolvable people, and compares membership.
A cohort with no retained operation has **unknown** import completeness, even when counts agree.

```sh
# Read-only; use next-cursor from the output to resume.
python manage.py reconcile_static_cohort_membership audit --limit 100
python manage.py reconcile_static_cohort_membership audit --after-cohort-id COHORT_ID --limit 100

# Inspect the dry run before explicitly starting selected repairs.
python manage.py reconcile_static_cohort_membership repair --cohort-id COHORT_ID
python manage.py reconcile_static_cohort_membership repair --cohort-id COHORT_ID --live-run
```

Repair uses the same durable operation lifecycle and pauses membership edits. It synchronizes the
resolvable ClickHouse subset; it cannot recover identifiers that never reached ClickHouse and are
no longer retained. A successful repair does not claim the original upload completed. No historical
repair runs during migration.

## Rollout and observation

1. Deploy the additive migration, personhog insertion lock and compatible workers.
2. Verify private storage, cleanup policy, dispatcher and observer execution. Confirm the
   `cohort_population_observe` Pushgateway job is publishing before relying on freshness alerts.
3. Enable `COHORT_POPULATION_DURABLE_ADMISSION_TEAM_ALLOWLIST` for selected teams. The default is
   `none`; expand after successful populations and recovery drills.
4. Disabling admission leaves existing operations recoverable. Keep workers and the schema deployed.

Existing Celery names and signatures remain adapters for previously queued work.

Worker counters use bounded labels:

- `cohort_population_outcomes_total{source,outcome}`
- `cohort_population_work_units_total{source,phase}`
- `cohort_population_recoveries_total{reason}`

The observer publishes unresolved operation counts (failed runs included, since they still hold
the cohort), recent outcomes, incomplete outcomes, and time since last progress of active runs
under `job="cohort_population_observe"`. Check `push_time_seconds` for observation
freshness. Cohort and operation IDs belong in structured logs; uploaded identifiers do not.

The charts repository owns `CohortPopulationInsertionErrors`, `CohortPopulationFailed`,
`CohortPopulationStalled` and `CohortPopulationObserveStale`, with corresponding runbooks under
`alerts/runbooks/`. The Grafana dashboards repository owns `static-cohort-population.json`.
Insertion RPC errors indicate possible inconsistency, not proof of permanent corruption.

## Code

- `products/cohorts/backend/population/`: admission, runner, recovery and observation
- `products/cohorts/backend/models/population.py`: durable record
- `posthog/personhog_client/interceptor.py`: allowlisted transport retries
- `rust/personhog-replica/src/storage/postgres/cohort.rs`: serialized membership insertion
