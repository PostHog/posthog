# Production runbook

## Where to run

Run the commands from a Django toolbox pod in the team's region.
Write scan directories under `/tmp` on that pod.
Copy only `summary.json` and actions-file outcome counts off the pod; the report holds customer keys.

## Before any write

1. Scan, and check that `summary.json` says `complete: true`.
2. Write down the verbs and row counts you plan to run, and get explicit approval.
3. Dry run each verb, and compare its `would_repair` count with the report.
4. Run a canary with `--apply --limit 10`, then check those keys with `person_inspect` after about a minute. ClickHouse applies published rows asynchronously.
5. Run the rest with `--resume` on the canary's actions file.

## Load

- Scans read ClickHouse in primary key order, one page of rows at a time. Increase `--pause-seconds` for a team with hundreds of millions of rows, or split it into chunks.
- Repairs write through personhog in batches. The default of 20 calls per second suits most teams. Lower it during an ingestion incident.

## When something looks wrong

- Many `skipped_changed` outcomes: ingestion is writing to these persons now. Rescan later.
- A run stops with a personhog `FAILED_PRECONDITION` or `DEADLINE_EXCEEDED` error after its retries: a merge or delete holds the person. Rerun with `--resume` a few seconds later. The persons reset endpoint answers 409 in the same case.
- `undelivered` in the summary line: some ClickHouse rows were not published. Those keys carry an `undelivered` action, so rerunning the same verb with `--resume` retries exactly them; every write is idempotent.
- A count far above what the scan predicted: stop, and inspect a few keys with `person_inspect` before continuing.
