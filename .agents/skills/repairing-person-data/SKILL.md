---
name: repairing-person-data
description: >
  Finds and repairs persons and distinct ids whose Postgres and ClickHouse state disagree for one team, and
  person deletions that never finished. Use when a team reports wrong, missing, duplicated or deleted-but-visible
  persons, after an interrupted project or person deletion, when a scan finds divergent persons, or when asked to
  restore, fold, merge, republish, bury or requeue persons. Covers the person_consistency scan and repair verbs,
  person_inspect, and person_deletion requeue.
---

# Repairing person data

Postgres (through personhog) is the source of truth for persons and distinct ids.
ClickHouse holds a versioned copy: the row with the highest version wins.
Almost every problem is one store holding a version, an owner or a tombstone the other does not.
The tools here find each disagreement, name its flavor, and repair it with a verb that writes only what still applies.

## The loop

1. **Scan the team** (read-only):
   `python manage.py person_consistency scan --team-id N --dir DIR`
   - Pass `--purged-at <ISO time>` when the team lost Postgres persons in a known purge. It dates each ghost as `after_purge` (restore it) or `historical` (leave it).
   - For a large team, run `plan --chunks K` first, then `scan --chunk i` per chunk in parallel, then `scan --phase postgres`, then `finalize`.
   - A stopped run continues with `--resume`.
2. **Read `DIR/summary.json` first.** It holds counts by flavor and verb, the largest groups, and `complete`. It names groups by verb and a hash, never by a key, so it is safe to quote. The scan directory itself is private to you, because the rows hold raw keys.
3. **Read `DIR/report.jsonl` only for the rows you act on.** It holds one row per key that is not ok: `kind`, `key`, `flavor`, `sub_flavor`, `verb`, `group`, `also`, and `evidence` (`pg`, `ch`). Keys are customer data: never paste distinct ids into chat, PRs or tickets. Use `key_hash` instead.
4. **Map rows to verbs** with [references/flavors.md](references/flavors.md). The report already names the verb. A row with `verb: null` is report-only: explain it, do not repair it.
5. **For each verb, run a dry run, then a canary, then the rest:**

   ```sh
   python manage.py person_consistency repair --dir DIR --verb V                      # dry run
   python manage.py person_consistency repair --dir DIR --verb V --apply --limit 10   # canary
   python manage.py person_consistency repair --dir DIR --verb V --apply --resume DIR/actions-V-apply-<ts>.jsonl
   ```

   - Narrow a run with `--group` or `--key`. Pace it with `--max-calls-per-second`.
   - Every key gets one line in the actions file. Read the outcomes, not just the counts.

6. **Verify with a fresh scan** into a new directory. The repaired keys must be gone from the new report.

## Order of verbs

Run them in this order, because later verbs read state that earlier ones fix:

1. `bury`: remove what Postgres deleted.
2. `restore`: rebuild lost persons, so their distinct ids have an owner.
3. `fold`, then `merge`: join persons that ClickHouse and Postgres split differently.
4. `merge_stale`: sends a stale person's ClickHouse-only properties to ingestion.
5. `republish`: last, so it publishes the final Postgres state.

Rescan between steps when a team has many rows. A verb skips any key whose state changed since the scan (`skipped_changed`), so a fresh scan picks it up again.

## Verbs that go through ingestion

`fold`, `merge` and `merge_stale` send events, and ingestion applies them asynchronously.
They never rewrite a diverged distinct id before ingestion has applied the event, so an unfinished group always shows up in the next scan.

- `merge` sends `$merge_dangerously`, waits up to a minute for ingestion to merge A into B, then points the shared ids at B (`merged`, ids `moved`). A merge that has not landed by then stays `merge_sent` (ids `awaiting_merge`): the next scan reports `merge` again, or `republish` once it landed.
- A **full** `fold` (the old person still has an id to merge from, and one of the two is identified) restores A with those ids, sends `$merge_dangerously` and waits the same way (`folded`, ids `moved`). A merge that has not landed shows up as `merge` in the next scan.
- A **light** `fold` (no id to merge from, or neither person identified) first sends A's ClickHouse-only properties to B (`properties_sent`). A later run that finds them on B moves the ids and tombstones A (`folded`, `moved`). If that run stops partway, the next scan reports the remaining ids for `republish`.
- `merge_stale` first sends properties (`merge_queued`); a later run raises and republishes the person.

Wait a few minutes between runs, then rescan and run the verb the new report names.
A verb that finds a person in the middle of a merge or delete retries for a few seconds, then stops. Rerun it with `--resume`.
The scan summary counts fold groups as `full` or `light`; the verb re-checks this at run time.

## Ambiguous groups

`ambiguous:X` means an old person's ids went to more than one person, or one person holds ids of several old persons.
No verb runs on these by default. Inspect the keys, decide which person should survive, and run `fold` or `merge` with `--pair OLD_UUID>NEW_UUID`.
Ids of the old person that went to other persons stay diverged; rescan and repair them afterwards.

## Inspecting single keys

`python manage.py person_inspect --team-id N --person-uuid U --distinct-id D` prints the same evidence and flavor for explicit keys, with distinct ids hashed. Use it to explain one row, or to check one key after a repair.
It also prints every ClickHouse row of the key (lightweight-deleted ones included), and for a person its activity log entries and its tombstone queue entry. These show when and how a person was deleted, merged or split.

## Unfinished deletions

A delete task that runs out of retries logs `delete_persons_async gave up` with every person it left undeleted and the time it gave up.
Export those lines as JSONL, then run `python manage.py person_deletion requeue --input F`. It is a dry run unless `--apply` is passed.
It re-queues the persons that still resolve, through the persons API path, and skips any person deleted after the give-up time, because new events revived it. Add `--recordings-only` to keep profiles.
The same line lists unmatched distinct ids. They only feed the AI training deletion, so `requeue` does not queue them; hand them to the AI training owners.
Do not requeue from the Celery broker's unacknowledged list: the broker redelivers those, or their tasks already re-ran.

## Safety rules

- Every write to production needs explicit approval from the person you work for, verb by verb. A dry run and a canary come first, every time.
- Never repair from a partial report (`complete: false`) without saying so. Missing chunks hide rows.
- `bury` refuses to tombstone persons Postgres never had once they pass 5% of a team's live persons, because a team that lost its persons needs `restore` instead. Pass `--force` only when a person explicitly confirms that those persons should be deleted.
- `fold`, `merge` and `merge_stale` send events to ingestion (`$set`, `$identify`, `$merge_dangerously`). These events land in the customer's events table and are billed like any other event. Canary first, and say so.
- Every ingestion merge marks the survivor identified. That is why `fold` merges only when one of the two persons is identified.
- A light `fold` keeps the survivor's `created_at`. A merge moves it to the earlier person.
- A team with person processing turned off is skipped by `fold` and `merge`, because ingestion drops their events.
- A `stray` (a live distinct id on a deleted person) is report-only: ingestion re-attaches the id on its next event.
- Ghosts of deleted teams, and `historical` ghosts, are report-only.
- Read [references/runbook.md](references/runbook.md) before running anything against production.
