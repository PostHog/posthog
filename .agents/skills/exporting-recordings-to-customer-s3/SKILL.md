---
name: exporting-recordings-to-customer-s3
description: >
  Runs a paid, staff-triggered export of a team's session recordings into an S3 bucket the customer owns,
  with the export_recordings_to_s3 management command.
  Use when a customer needs recordings kept past retention (litigation, legal hold, forensics, compliance archive),
  when asked to quote, price, start, monitor or check an export of recordings to a customer's bucket,
  or when a customer asks how to play back an exported .phrec file.
  Covers the quote, the customer's S3 integration and KMS setup, starting the run, monitoring it and handing over the result.
---

# Exporting recordings to a customer's S3 bucket

Read [the export README](../../../products/replay/backend/temporal/export_recordings/README.md) first.
It explains the run, the bucket layout, the file format and what the customer sets up.

The export costs us real money and the customer pays for it.
So the job has two halves with a person in between: quote, then wait for a go-ahead, then start.

## Decisions that are not yours

Stop and ask the person you work for before you:

- **Start an export.** Only start one when a person confirms the customer accepted the quote and billing cleared it.
  A request to "export recordings for X" means quote first.
- **Name a price or share the quote with anyone.** The command prints our cost. Sales sets the price.
- **Pass `--allow-cross-region`.** Cross-region transfer adds cost the customer must have agreed to.
- **Raise `--max-parallel-shards` above the default** on a large export. More shards load recording-api harder.

## Where to run

Run every command in a toolbox pod in the team's region (`prod-us` or `prod-eu`).
[The toolbox CLI](../../../tools/infra-scripts/clitools/README.md) claims one.
A toolbox pod has what the command needs: ClickHouse for the quote, object storage for quotes and session lists, and Temporal to start the workflow.
The shards run on the session replay workers, not in the pod.

Run each command with `kubectl exec <pod> -- python manage.py export_recordings_to_s3 ...`.
For a session list, first copy the file into the pod with `kubectl cp`.

## Steps

### 1. Pin down the selection

You need the team ID, the region (US or EU), the date range (UTC days, inclusive) and the bucket's AWS region.
To export only some sessions in the range, you also need one of:

- a saved recordings filter (`--playlist <short id>`), for a selection like "sessions that visited this URL" or "sessions from this country". Have the customer, or the person, build the filter in the recordings list and save it, so the customer sees exactly what they get. The short ID is in the filter's URL (`savedFilterId=`). The filter's own date range is ignored: the quote's range applies.
- a file of session IDs (`--session-ids-file`).

Filters on event properties, such as country, scan events over the whole range and can take minutes on a large team.
Each day can select at most 100,000 sessions. The quote names the day that goes over; split the range or narrow the filter.
A session belongs to the day it started on.
The range must end before today (UTC). The command refuses a range that includes today.
Recordings past their retention are gone and cannot be exported.

### 2. Quote

```sh
python manage.py export_recordings_to_s3 --quote --team-id <id> --region <bucket region> \
    --date-from <yyyy-mm-dd> --date-to <yyyy-mm-dd> [--playlist <short id> | --session-ids-file ids.txt]
```

Report the quote ID, the session count, our cost, the estimated duration, the best-effort session count and the valid-until time.
Best-effort sessions expire within days and may expire before their shard runs. Say so plainly.
A quote is valid for 7 days. After that, quote again: more data moves to Glacier IR and the cost rises.

### 3. Check the customer's setup

Before the start, confirm with the person that the customer has:

- a role-based AWS S3 integration in that project (note its integration ID), whose role trusts PostHog's recording-exports role for the region (the README lists the ARNs). An existing batch export role works once it also trusts that role,
- a role that allows `s3:PutObject` and `s3:AbortMultipartUpload` on the bucket and prefix,
- for a KMS-encrypted bucket, KMS permissions on the role and a key policy that allows the role, plus the key ID or ARN (not an alias),
- the bucket in the same AWS account as the role,
- a lifecycle rule that aborts incomplete multipart uploads, so a failed shard's unfinished parts do not stay in their bucket.

The README lists the exact requirements to send them.

### 4. Start, after the go-ahead

```sh
python manage.py export_recordings_to_s3 --quote-id <quote id> --integration-id <id> --bucket <bucket> \
    --region <bucket region> --prefix <prefix> [--kms-key-id <key id or ARN>]
```

Without `--yes`, the command prints the quote and the destination and stops, because an exec has no terminal to answer its prompt.
Show that output to the person.
Rerun with `--yes` only after they confirm that exact quote and destination.
Keep the printed workflow ID.

### 5. Monitor

```sh
python manage.py export_recordings_to_s3 --status <workflow id>
```

A large export runs for hours or days.
A failure on credentials or a missing integration is permanent: the customer must fix the role, then you start a new run from a fresh quote.
Other shard failures retry on their own and resume from their last checkpoint.

A shard that still fails after its retries does not stop the run. The run writes its summary and then ends as failed, with the failed shards in the error and in `summary.json` under `failed_shards`.
Ask the person before you rerun them. Then start the same quote again with `--shards <the failed list>` and the same `--shards-per-day`.
A quote can start again only after a failed run, so a second start of a running or finished export is refused.

### 6. Hand over

When the status is completed, `summary.json` is in the bucket under `{prefix}/{team_id}/{run_id}/manifests/`.
Each run, including a rerun of failed shards, has its own `run_id` folder.
Report its session totals: exported, deleted, expired, missing, and `deleted_before_run`.
Explain any non-zero count other than exported.
Tell the customer they can check each file against the `sha256` in the manifests, and play a file back in Replay's file playback page.

## Done means

- The person has the quote figures, and you started nothing without their go-ahead.
- Or the run completed and you reported the summary totals.
