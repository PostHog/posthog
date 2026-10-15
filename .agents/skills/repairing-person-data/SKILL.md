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
2. **Read `DIR/summary.json` first.** It holds counts by flavor and verb, the groups, and `complete`. It never names a key, so it is safe to quote.
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

1. `detach_stray` and `bury`: remove what Postgres deleted.
2. `restore`: rebuild lost persons, so their distinct ids have an owner.
3. `fold`, then `merge`: move distinct ids between persons.
4. `merge_stale`, run twice: the first run sends properties to ingestion, and the second, after ingestion applied them, raises and republishes.
5. `republish`: last, so it publishes the final Postgres state.

Rescan between steps when a team has many rows. A verb skips any key whose state changed since the scan (`skipped_changed`), so a fresh scan picks it up again.

## Inspecting single keys

`python manage.py person_inspect --team-id N --person-uuid U --distinct-id D` prints the same evidence and flavor for explicit keys, with distinct ids hashed. Use it to explain one row, or to check one key after a repair.

## Unfinished deletions

`python manage.py person_deletion stuck --output F` lists delete tasks the Celery broker never saw acknowledged. It only reads the broker.
`python manage.py person_deletion requeue --input F` re-queues the persons that still resolve, through the persons API path. Add `--recordings-only` to keep profiles.
Both are dry runs unless `--apply` is passed.

## Safety rules

- Every write to production needs explicit approval from the person you work for, verb by verb. A dry run and a canary come first, every time.
- Never repair from a partial report (`complete: false`) without saying so. Missing chunks hide rows.
- `bury` refuses to tombstone persons Postgres never had once they pass 5% of a team's live persons, because a team that lost its persons needs `restore` instead. Pass `--force` only when a person explicitly confirms that those persons should be deleted.
- `fold` and `merge` send events to ingestion (`$set_once`, `$merge_dangerously`). These events land in the customer's events table and count toward usage. Canary first, and say so.
- `fold` keeps the survivor's `created_at`. Only `merge`, through ingestion, moves it to the earlier person.
- Ghosts of deleted teams, and `historical` ghosts, are report-only.
- Read [references/runbook.md](references/runbook.md) before running anything against production.
