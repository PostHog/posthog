# Worked examples

Three merged PRs, as shipped and after all five passes. Read these when the rule in `SKILL.md` is clear but you want to see it applied end to end.

Example 1 is a reorder: the same facts, in the order a reviewer needs them.
Examples 2 and 3 are cuts.
All three come out shorter, because bullets are how you cut to the facts that matter, not how you restate a paragraph at greater length.

The measurements behind these rules live in the PR that introduced them, reachable from `git log` on `SKILL.md`. They are provenance for whoever edits this skill, not instructions for writing a body.

---

## Example 1: the effect was three bullets down

[fix(dashboards): tolerate legacy keys in persisted dashboard filters](https://github.com/PostHog/posthog/pull/78235).

### Problem as shipped, 82 words

```markdown
- `Dashboard.filters` persists opaquely, and readers rebuild the `extra="forbid"` `DashboardFilter` from it on every tile refresh.
- One legacy key in the blob (`filter_test_accounts`, top-level `breakdown`) fails that validation and errors every tile on the dashboard.
- The dashboard UI merges persisted filters into every save, so the app cannot repair a broken blob.
- A support ticket hit exactly this: a REST client wrote the legacy insight-format key `filter_test_accounts`, and the dashboards stayed broken until the blob is rewritten by hand.
```

### After pass 1, 71 words

```markdown
- One legacy key in a dashboard's saved filters errors every tile on that dashboard.
- The UI merges saved filters into every save, so nobody can repair the blob from the app. It stays broken until someone rewrites it by hand.
- `Dashboard.filters` persists opaquely, and readers rebuild the `extra="forbid"` `DashboardFilter` from it on every tile refresh.
- `filter_test_accounts` and a top-level `breakdown` are the keys that fail that validation.
```

Every fact survived. The reviewer now learns that tiles break and nobody can unbreak them before they learn which class validates what.

### The lower half

As shipped, the two sections a reviewer needs ran 190 words and the two under them ran 224. Three moves fix the ratio:

| Text                                                                                                                             | From                       | To                                     |
| -------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | -------------------------------------- |
| "A 400 for unknown keys on write would block saving: the UI echoes persisted blobs back into saves"                              | Agent context, last bullet | Changes, as a bullet                   |
| "Ran `pytest` on the two touched test files (52 passed), repo-wide `mypy` (clean), and `hogli ci:preflight --fix` (no failures)" | Testing                    | Deleted. The checks report all three   |
| "The existing PATCH round-trip test in `test_dashboard.py` guards the wiring"                                                    | Testing                    | Deleted. An existing test still passes |

The rejected alternative is the one line a reviewer needs to judge the design. It sat below the changelog checkbox.

---

## Example 2: a long causal chain

[fix(data-warehouse): recognize Neon's pooler rejection of libpq options](https://github.com/PostHog/posthog/pull/77899). Problem and Changes only.

### As shipped, 297 words

```markdown
## Problem

Transaction-mode connection poolers reject the libpq `options` startup parameter, so `_connect_with_options_fallback` drops `options` and reconnects. The match is on the exact wording those poolers use:

FATAL: unsupported startup parameter: options

Neon's pooled endpoint names the offending setting instead of the parameter:

ERROR: unsupported startup parameter in options: statement_timeout.
Please use unpooled connection or remove this parameter from the startup package.

`"unsupported startup parameter: options"` is not a substring of that, so the fallback never fires and the connect just fails.

On the CDC path that connect is the first thing `cdc_extract_activity` does, and the stream reader always sends `options` (`statement_timeout=1800000 -c idle_in_transaction_session_timeout=0`). So every extraction run against a Neon pooled endpoint fails at `stream_reader.connect()`, forever. It classifies as a generic retryable `connection_failed`, so the user sees "Could not connect to the source database. PostHog will keep retrying — if this persists, check that the database is reachable and accepting connections" for a database that is reachable and perfectly healthy. There is nothing they can do to make that message go away, because it isn't describing their problem.

One source has been in this state since the day it was created. It never had a single successful extraction run.

## Changes

Match on the prefix `unsupported startup parameter in options` so any setting Neon names is covered, alongside the existing exact-wording and RDS Proxy matches.

The stale comment on the CDC stream reader claimed CDC sources never sit behind a pooler that rejects `options`. They do. Neon's pooler serves the `pg_logical_slot_peek_binary_changes` calls the reader uses just fine, so dropping the two server-side timeouts is the difference between working change capture and none at all. Updated it to say so, and to note that the activity's start-to-close and heartbeat timeouts still bound a stalled peek once the server-side ceiling is gone.
```

### After the remaining passes, 197 words

````markdown
## Problem

- Transaction-mode connection poolers reject the libpq `options` startup parameter.
- `_connect_with_options_fallback` drops `options` and reconnects when it sees the exact wording those poolers use:

```
FATAL:  unsupported startup parameter: options
```

- Neon's pooled endpoint names the setting instead of the parameter:

```
ERROR:  unsupported startup parameter in options: statement_timeout.
```

- That is not a substring of the match, so the fallback never fires.
- The CDC stream reader always sends `options`, and that connect is the first thing `cdc_extract_activity` does.
- Every extraction run against a Neon pooled endpoint therefore fails at `stream_reader.connect()`, forever.
- It classifies as a retryable `connection_failed`, so the user is told to check a database that is reachable and healthy.
- One source has never had a successful extraction run since the day it was created.

## Changes

- The match now uses the prefix `unsupported startup parameter in options`, so any setting Neon names is covered.
- The stream reader's comment claimed CDC sources never sit behind a pooler that rejects `options`. They do, and the comment now says so.
- Dropping the two server-side timeouts is the difference between working change capture and none.

> [!NOTE]
> Retry and classification behavior do not change. This makes the connection succeed where it currently cannot be opened at all.
````

### What the passes did

Pass 3 cut 100 words:

| Cut                                                                                                    | Why                                                                                       |
| ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| The second line of Neon's error, and the full quoted user-facing message                               | The reader needs the phrasing that breaks the match, not the whole string                 |
| `statement_timeout=1800000 -c idle_in_transaction_session_timeout=0`                                   | "Always sends `options`" is the fact. The values themselves change nothing for the reader |
| "There is nothing they can do to make that message go away, because it isn't describing their problem" | Second half of a reason pair. The bullet above it already says the database is healthy    |
| "Neon's pooler serves the `pg_logical_slot_peek_binary_changes` calls the reader uses just fine"       | Supports a claim nobody will dispute                                                      |
| The start-to-close and heartbeat timeout note                                                          | Belongs in the code comment it describes, and is there                                    |

Pass 4 split the 76-word failure chain, which was the densest sentence in the description, into the five links a reviewer checks one at a time.

Both fenced blocks survived untouched. Pass 4 governs prose only.

Pass 1 came later than this rewrite, and the rewrite fails it. The lead is a fact about libpq, while the effect sits in bullets 6 and 8. Cutting did not fix that, and no amount of it would. Open with them instead:

> - Data warehouse syncs from a Neon pooled endpoint have never worked. One source has failed every extraction run since the day it was created.
> - The user is told to check a database that is reachable and healthy, because the failure classifies as a retryable `connection_failed`.

That first bullet is also the one claim here the claim rules in pass 3 reach. "Never worked" and "every run" are things the author saw, not behavior a reader can check against the code. The bullet owes a link to the run or the error tracking issue behind it. Every other bullet in this example describes behavior and needs none.

---

## Example 3: two independent reasons in one paragraph

[fix(flags): drop custom codecs from flag_evaluations columns](https://github.com/PostHog/posthog/pull/77910). Problem and Changes only.

### As shipped, 190 words

```markdown
## Problem

Migration 0292 gave `flag_evaluations` explicit per-column codecs, mirroring the pattern the events tables use: `ZSTD(1)` on the plain String columns, `DoubleDelta, ZSTD(1)` on the datetime columns. That's the wrong call here. Compression on this cluster is tuned centrally at the ClickHouse server level, so pinning a codec on a column just takes it out of that cluster-wide tuning instead of improving anything. DoubleDelta specifically pays off when values trend with the sort order, and `flag_evaluations` sorts by `(team_id, flag_key, toDate(timestamp), cityHash64(distinct_id))`, which doesn't lead with time, so it isn't earning its keep there either.

## Changes

Migration 0293 sets the codecs 0292 declared and then removes them with `MODIFY COLUMN ... REMOVE CODEC`, across the sharded data table, the writable distributed table, and the read-path distributed table. Setting before removing means the migration applies cleanly whether 0292 already ran (codecs exist) or a fresh install already built the tables codec-free from the updated DDL (`REMOVE CODEC` errors on a column with no codec).

`posthog/models/flag_evaluations/sql.py` is the shared column template other DDL reads from, so the per-column `CODEC(...)` clauses are stripped there too. The HCL golden/SQL mirrors and the `test_schema.ambr` snapshot are regenerated to match.
```

### After the remaining passes, 111 words

```markdown
## Problem

- Migration 0292 gave `flag_evaluations` per-column codecs, mirroring the events tables.
- This cluster tunes compression centrally, so pinning a codec only takes the column out of that tuning.
- DoubleDelta pays off when values trend with the sort order. `flag_evaluations` sorts by `(team_id, flag_key, toDate(timestamp), cityHash64(distinct_id))`, which does not lead with time.

## Changes

- Migration 0293 sets the codecs 0292 declared, then removes them with `MODIFY COLUMN ... REMOVE CODEC`, across all three tables.
- `REMOVE CODEC` errors on a column with no codec, so setting first keeps the migration safe on a fresh install.
- `posthog/models/flag_evaluations/sql.py` is the shared column template, so the `CODEC(...)` clauses are stripped there too.
- The HCL goldens and the `test_schema.ambr` snapshot are regenerated.
```

### What the passes did

Pass 3 cut 79 words:

| Cut                                                                          | Why                                                                                  |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `ZSTD(1)` on Strings, `DoubleDelta, ZSTD(1)` on datetimes                    | Exact values. The bullet above already says what the codecs were for                 |
| "That's the wrong call here"                                                 | The next two bullets say why. The verdict adds nothing they don't reach on their own |
| "instead of improving anything", "so it isn't earning its keep there either" | Restate the claim already made in the same sentence                                  |
| The three table names, listed in full                                        | "All three tables" is enough. The migration names them                               |

Pass 4 separated the two independent reasons the codecs were wrong. They were welded into one paragraph, so a reviewer who wanted to dispute the DoubleDelta argument had to disentangle it from the central-tuning argument first.

Nobody sees this change, which is the case pass 1 is easiest to skip on. There is still an effect, and it is not "migration 0292 did a thing":

> - The codecs on `flag_evaluations` take those columns out of the cluster's central compression tuning and buy nothing back.

The line check's first item is what makes this a rewrite rather than a reformat: the body has to come out shorter. Both cut examples do, 297 words to 197 and 190 to 111, and the reorder in example 1 came out shorter too.
