# Runbook: draining cyclotron V1 hogflow jobs into V2

Empties the cyclotron **V1** (legacy postgres) backend of parked `hogflow` jobs so V1 can be
decommissioned, instead of waiting ~90 days for natural drain. Legit parked runs are relocated
into **V2** on their existing schedules; the corrupt far-future rows are deleted.

The script is `relocate-cyclotron-v1-jobs.ts` in this directory. It is **dry-run by default** and
never deletes from V1 until each relocated id is confirmed present in V2.

Run it **once per region** (prod-us and prod-eu have separate V1 and V2 databases).

> Two databases both hold a table called `cyclotron_jobs`. V1 is the source we are emptying; V2 is
> the target. The V1 database is the one whose `cyclotron_jobs.state` accepts `available`/`running`/
> `paused` and that also has a `cyclotron_dead_letter_metadata` table. Confirm you have the right
> URLs before applying.

## Before you start

You need, for the target region:

- `CYCLOTRON_V1_DATABASE_URL` — the legacy (V1) cyclotron database (source, gets emptied).
- `CYCLOTRON_V2_DATABASE_URL` — the cyclotron-node (V2) database (target).

## Step 1 — Stop the V1 drain worker (MANDATORY, do this first)

The legacy drain worker `cdp-cyclotron-worker-hogflows-pg-legacy` (2 pods/region) actively dequeues
V1 hogflow jobs. If it is running while the script runs, both can grab the same job → double
execution / double send. **Scale it to 0 in the target region and confirm 0 pods before continuing.**

KEDA manages the deployment's replica count, so a plain `kubectl scale ... --replicas=0` is reverted
within seconds by the ScaledObject. Use one of these instead:

- **Fast / reversible (recommended for the operation window)** — pause KEDA and hold at 0 replicas.
  The deployment and ScaledObject are both named `cdp-cyclotron-worker-hogflows-pg-legacy` in
  namespace `cdp-cyclotron-worker-hogflows-pg-legacy`:

  ```bash
  # target the correct cluster/context for the region (posthog-prod = us, posthog-prod-eu = eu)
  kubectl -n cdp-cyclotron-worker-hogflows-pg-legacy \
    annotate scaledobject cdp-cyclotron-worker-hogflows-pg-legacy \
    autoscaling.keda.sh/paused-replicas=0 --overwrite
  ```

  Reverse later by removing the annotation:
  `kubectl -n cdp-cyclotron-worker-hogflows-pg-legacy annotate scaledobject cdp-cyclotron-worker-hogflows-pg-legacy autoscaling.keda.sh/paused-replicas-`

- **GitOps (permanent, part of teardown)** — in
  `apps/cdp-cyclotron-worker-hogflows-pg-legacy/values.prod-us.yaml` (and `values.prod-eu.yaml`) set:

  ```yaml
  autoscaling:
    minPods: 0
    maxPods: 0
  ```

  With `minPods == maxPods` the chart renders `replicas: 0` and emits no ScaledObject, so the worker
  stays at 0. Merge and let ArgoCD sync.

Confirm 0 pods before running the script:

```bash
kubectl -n cdp-cyclotron-worker-hogflows-pg-legacy get pods
```

## Step 2 — Baseline counts (V1 database)

```sql
SELECT count(*) FILTER (WHERE scheduled <= now() + interval '1 year') AS legit,
       count(*) FILTER (WHERE scheduled >  now() + interval '1 year') AS corrupt
FROM cyclotron_jobs
WHERE queue_name = 'hogflow' AND state = 'available';
```

Expect roughly **69 legit** and **4 corrupt** (verified 2026-07-21; read the live numbers, they may
drift).

## Step 3 — Dry run

```bash
CYCLOTRON_V1_DATABASE_URL=... CYCLOTRON_V2_DATABASE_URL=... \
  tsx src/cdp/scripts/relocate-cyclotron-v1-jobs.ts --env prod-us
```

Check that the printed legit/corrupt counts match Step 2, that the V1/V2 database identifiers are the
ones you expect, and that the scheduled ranges look sane (legit within ~90 days out, corrupt far in
the future). No writes happen in this mode.

## Step 4 — Apply

```bash
CYCLOTRON_V1_DATABASE_URL=... CYCLOTRON_V2_DATABASE_URL=... \
  tsx src/cdp/scripts/relocate-cyclotron-v1-jobs.ts --env prod-us --apply
```

The script writes the legit rows to V2 (preserving id + scheduled), verifies each id is present in
V2, deletes only the verified ids from V1, then deletes the corrupt ids. It prints a summary:
`relocated N`, `deleted-corrupt M`, and the remaining V1 count (should be 0).

Re-running `--apply` is safe: it only acts on what is still in V1, so a partial run just needs to be
run again.

## Step 5 — Confirm V1 is empty (V1 database)

```sql
SELECT count(*) FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND state = 'available';
```

Expect **0**. Repeat Steps 1–5 for the other region.

## Step 6 — Drop the dead-letter backlog (optional, safe to run anytime)

The V1 dead-letter queue holds old, unreplayable `fetch` jobs (all >1yr old, reason "Could not parse
job parameters"). These are not handled by the script. Run this directly against the **V1 database**
whenever convenient:

```sql
DELETE FROM cyclotron_jobs WHERE queue_name = '_cyclotron_dead_letter' AND state = 'available';
DELETE FROM cyclotron_dead_letter_metadata;
```

(~814 rows at last check.)

## Step 7 — Teardown ordering (not part of the urgent path)

- **Email is handled separately — do not tear V1 down too early.** The `email` queue (~840 rows)
  self-drains via its own live worker `cdp-cyclotron-worker-email-legacy-pg`, which sends each email
  inline through SES when it comes due, in a single window **2026-07-25 16:28 → 07-26 08:28 UTC**.
  Do **not** remove that worker or tear down V1 before ~**2026-07-27**. After the window, confirm the
  V1 email backlog is drained:

  ```sql
  SELECT count(*) FROM cyclotron_jobs WHERE queue_name = 'email' AND state = 'available';
  ```

  Expect 0, then the email worker can be removed.

- Once hogflow is drained (Step 5 = 0 in both regions), the `cdp-cyclotron-worker-hogflows-pg-legacy`
  app can be removed (or left at 0 replicas via the GitOps override in Step 1).

- Only tear down V1 itself once hogflow, the dead-letter queue, and email are all confirmed empty.
