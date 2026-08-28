---
name: evaluating-warehouse-sources
description: Evaluate a Data warehouse source change where CI cannot — against live vendor credentials, real data volume, repeated syncs, pre-existing tables, and production egress. Use before merging or releasing a new source or table; after changing pagination, incremental cursors, primary keys, partitioning, report parsing, or auth/scopes; when asked to run a live smoke sync, verify a source against a real account, or check a landed table for duplicates and silent gaps. Covers the contract-assumption audit, the live smoke protocol and credential matrix, landed-data SQL invariants, adversarial replay fixtures, and the post-merge fleet watch. Not for building a source (implementing-warehouse-sources), finding missing endpoints (auditing-warehouse-source-coverage), or diagnosing one customer's failing sync (triaging-warehouse-sync-tickets).
---

# Evaluating warehouse sources where CI cannot

CI for `products/warehouse_sources/backend/temporal/data_imports/sources/**` mocks every vendor call.
The sandbox holds no vendor credentials, so a green suite proves the code is consistent with the author's model of the API — never that the model is right.
When the model is wrong, the fixtures are wrong the same way, and the tests pass.
Two real tests have pinned a bug as the contract: a Twilio case asserting the wrong key-type rejection (#78033) and a Checkout.com case asserting that budget exhaustion "stops cleanly" (#82115).

The defects that escape this way are rarely loud.
The dominant class is **silent incompleteness under a green status**: the sync reports `Completed` while landing zero rows (#82961, #78127), one page (#78129), a clamped window (#82115), silently skipped file rows (#82957), or duplicated keys (#82959, #82099).
Loud failures get customer reports within days; silent ones surface weeks later, only when someone reconciles the landed table against the vendor's own dashboard.

This skill is the repeatable evaluation that runs where CI cannot.
It was distilled from a month of shipped fixes; [references/defect-catalog.md](references/defect-catalog.md) records each one with the check that would have caught it.
Read the catalog once to calibrate suspicion, then run the tiers below.

## The five escape classes

| Class                                                                                                                                                    | Example PRs                            | What CI lacked                                 |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- | ---------------------------------------------- |
| **1. Inferred vendor contract** — required params, envelope keys, cursor names, id fields, domain topology exist only in the author's head and fixtures  | #79119, #82961, #78129, #78983, #82159 | one authenticated request per endpoint         |
| **2. Silent success** — a code path returns normally with fewer rows than the vendor holds                                                               | #78127, #82115, #82957, #78129         | row-count parity against the vendor's own UI   |
| **3. Credential-instance variance** — key types, per-endpoint scopes, plan/add-on gating, OAuth manifest grants, regions                                 | #78033, #78035, #78134, #77920, #80824 | deliberately differentiated live accounts      |
| **4. Keys, merges, partitions, restatements** — correctness only breaks across overlapping runs, regenerated files, or days of vintages                  | #82959, #82099, #82974, #82973         | multi-run syncs over real, drifting data       |
| **5. Environment & pre-existing state** — production egress topology, engine-variant catalogs, brownfield Delta tables, privilege-filtered introspection | #80823, #84705, #84740, #82273         | prod-like proxies, real clusters, seeded state |

## Scope the evaluation to the change

- **New source or new table**: all four tiers. Tier 1 is what `releaseStatus` gates on — see "Record the verdict".
- **Pagination, cursor, incremental, resume changes**: Tiers 0, 1 (probes + double sync + kill/resume), 3 (exhaustion + resume fixtures).
- **Auth, scopes, key handling, OAuth manifest changes**: Tiers 0 and 1 with the credential matrix.
- **Parser / report-file changes**: Tiers 0, 3 (malformed-body and format-era fixtures), 2 after any live sync.
- **New transport (WebSocket, gRPC, vendor SDK socket)**: Tier 1 must include the egress-proxy check.
- **SQL-database source introspection**: Tier 1 against a real cluster of that engine, plus the restricted-role fixtures in Tier 3.
- **Schema/settings APIs that mutate existing rows** (bulk updates, migrations): Tier 3 brownfield checks — assert post-call state, never just HTTP status (#82273).

## Tier 0 — contract-assumption audit (every PR, no credentials)

**1. Write the claims ledger.**
List every assumption the diff makes about vendor behavior: endpoint paths exist, required params, response envelope/wrapper keys, cursor field names and termination signal, sort order (and that `sort_mode` matches it), primary-key uniqueness scope, whether the server-side filter actually filters, field- or scope-gated attributes, rate-limit headers, domain topology (regions, sandbox domains), API version behavior.
For each claim, record the strongest evidence backing it, ranked: captured live response > vendor OpenAPI spec > vendor prose docs > vendor SDK source > another connector (Airbyte/Fivetran) > the author's own fixture.
Vendor prose can disagree with itself — Decagon's export doc named its cursor three different ways and the code picked a wrong one (#78129) — so treat docs-only evidence as provisional.
**Every claim whose only evidence is a fixture the author wrote goes on the Tier 1 live-check list**, and into the PR body as unverified if Tier 1 can't run.

**2. Sweep for silent-success paths.**
Enumerate every way the sync can return normally, and ask what data each path can leave behind:

- warn-and-skip loops with no bounded skip ratio — months of parseable files skipped row by row (#82957)
- budget, page-cap, or horizon exhaustion that sets a flag and returns — partial data under `Completed` (#82115); exhaustion must raise a typed retryable error, and horizons are defaults, never clamps on explicit user config
- pagination that ends on a missing cursor while the page is full — the truncation signature (#78129); warn on it at minimum
- termination counters fed by rows fetched rather than rows kept after dedupe (#80184), with a no-progress guard for servers that ignore the page param
- discovery failures that prune tables instead of propagating — only 401/403 may degrade to a static catalog (#79119)
- catch-all `except` that collapses "can't know" into "known empty" (#84740) — prefer three-state answers (present / absent / undetermined)

**3. Mechanical checks.**

- Partition key is a pure function of an immutable field, ideally of the primary key (`md5(id)` bucket pattern). Delta merge matches key AND partition, so a partition derived from a mutable or optional served field silently duplicates rows (#82959).
- Primary key is unique table-wide, not per parent; business keys, never positional `(file_id, row_index)` keys, for files the vendor regenerates (#82099). Synthetic hash keys cover only stable fields (#80000).
- API error handling logs a bounded response-body excerpt — the status line alone made #79119 undiagnosable from logs.
- Every distinct failure cause yields a distinct, actionable message (#78034); non-retryable matchers are ordered most-specific-first, plan-gating before blanket 403 (#78134); never advise an action that can't fix the cause — "re-authorize" cannot grant a manifest-gated permission (#80824).
- Duplicated per-vendor lists (field sets, scopes) are cross-checked by a test: OAuth manifest ↔ table catalog (#77920), duplicate field lists (#80824), every endpoint declares a scope (#78035).

## Tier 1 — live smoke sync (the part CI can never do)

**Credentials.**
Prefer a vendor sandbox or trial (Stripe test mode, Gladly's sandbox domain, Twilio trial); some vendors need a support-requested dev account — start that request early, it's the long pole.
Record which credential instance you tested: plan tier, add-ons, key type, granted scopes. Never the secret itself — keep secrets in local env vars, out of PR bodies, commits, and agent transcripts.
Cloud agent sandboxes hold no vendor secrets, so an agent's Tier 1 deliverable is usually the **runbook**: the exact probe requests, sync steps, and expected assertions for a human (or credentialed environment) to execute. Writing that runbook is part of this skill, not an excuse to skip it.

**1. Probe each claim.**
For every entry on the Tier 0 live-check list, one authenticated request **through the source's own transport** (its headers, encoding, and body construction are part of the claim — a bare curl can pass where the source fails).
Assert the status, and that the source's own parser yields rows from the real body: the envelope check that would have caught fan-out ids the real API never sends (#82961).
Probe filters with a cutoff that should exclude everything; rows still returning means the filter is silently ignored.

**2. First sync, for real.**
Run the dev stack (`hogli start`), connect the source through the actual wizard with the sandbox credentials — this also exercises `validate_credentials`, the config form, and the schema picker — enable every changed table, and sync.
Then compare row counts per table against the vendor's own dashboard or export.
Count parity with the vendor's UI is the single check that caught both the one-page truncation (#78129) and a missing report-variant stream that a rival pipeline surfaced (#82956).

**3. Run the landed-data invariants** — Tier 2, below — against every synced table.

**4. Sync again, then kill one.**
An immediate second sync must be idempotent: `count()` still equals `uniqExact(pk)` on merge tables, counts unchanged on full refresh.
Then interrupt a sync mid-run and resume: boundary rows must be neither skipped nor duplicated, and a completed job must not re-append its final page on retry (#80183).

**5. Credential matrix** (when the change touches auth, scopes, or gating).
Cells worth holding accounts for: narrow-scope key, full-scope key, lowest plan, plan with the relevant add-on, OAuth install where supported, wrong region, wrong account.
Per cell assert: the connect verdict; that picker gating names the missing scope or plan as the vendor spells it; and that a sync either lands rows or fails loudly with copy the user can act on.
This is the class where one string covering five causes (#78034), a rejected documented key type (#78033), and a plan-gated 403 reading as a scope problem (#78134) all shipped.

**6. Egress topology** (any non-`requests` transport).
Production egress rides a CONNECT proxy whose goproxy core answers `HTTP/1.0 200 OK`; `requests`/urllib3 tolerate that, other stacks may not — the Framer WebSocket transport failed on every production connect while all tests passed (#80823).
Before merging a novel transport, run `validate_credentials` through a proxy speaking exactly that dialect (the fake-proxy test in `framer/tests` is the reference).

## Tier 2 — landed-data invariants

Run the parameterized queries in [references/invariant-queries.md](references/invariant-queries.md) after any live sync: primary-key integrity, duplicate hotspots, month-gap scan, parent/child coverage join, restatement sanity for report-based sources, zero-row-completion detection.
Several of these are lifted verbatim from the audits that found shipped defects — they are the acceptance criteria the fixes were verified against.

**Post-merge watch: hand it to self-driving first.**
Tier 1 verifies one account; production is many, and Self-driving is already standing watch there.
The data-warehouse Signals scout (`products/signals/skills/signals-scout-data-warehouse/SKILL.md`) continuously sweeps every enabled project for exactly the fleet-side signatures this tier cares about — armed-but-failed schemas, silent staleness behind a green `Completed`, dead webhook channels, row-volume cliffs — and files deduped reports into the Inbox.
Wire the change into that standing watch instead of reinventing it:

- **Leave the scout a note when the change deploys**: `scout-notes-create` targeting `signals-scout-data-warehouse`, `expires_at` about a week out. Name the source type, the deploy date, and the failure signatures to expect (new error strings, tables whose counts should jump, formats that changed). Notes are advisory context every run reads first — they point the scout's next runs at the source and let it date onsets to the deploy instead of calling them unexplained.
- **Check the Inbox over the next 24–72h** for reports naming the source type (`inbox-reports-list`, search by source name). A scout report that traces to the change is an escaped defect: fix it, then feed the ratchet — catalog entry, fixture, invariant.
- **Know what the scout cannot see.** It audits status, freshness, and volume; it never checks key integrity, parent/child coverage, or restatement math. Queries 1–7 in the reference file stay yours to run.
- **For a cross-fleet sweep**, the replica queries in the same reference file (setup in `/auditing-warehouse-source-coverage` step 2) still apply. Connection counts and per-team results are internal operational data — use them, never commit them.

If Tier 1 was impossible pre-merge, say so in the PR and name the watch — a scout note plus a named inbox-checker counts; "worth a live smoke sync after merge" with nobody on the hook does not.

## Tier 3 — adversarial replay (no credentials, graduates into CI)

These are fixtures and tests that live in the source's `tests/` and run in CI forever after — the point is that they encode _vendor reality_, not the author's assumptions, so build them from captured or historical material wherever possible.

- **Malformed bodies**: HTML error page, JSON error, blank-prefixed body, truncated stream fed to the parser must raise a loud, named error — `csv.DictReader` happily parses `<html>` into a column named `html` (#82159).
- **Format eras**: real historical file variants (ragged widths, trailing delimiters, header variants); invariant: any file with data rows loads at least one row or raises, and the skip ratio is capped (#82957).
- **Regeneration replay**: two overlapping generations of the same logical rows, fresh file ids, drifted values → keep-last by business key, `count() == uniqExact(key)` after both (#82099, #82959).
- **Exhaustion**: force the budget/page cap to a tiny value → typed retryable error, never a normal return; assert the message carries the marker the retry classifier matches (#82115).
- **Kill/resume**: interrupt after each checkpoint boundary → no skipped or duplicated rows; completed state cleared so retries don't re-append (#80183).
- **Brownfield**: seed a Delta table in the pre-change schema, append a new-shape batch, and observe what actually happens to types and existing rows — typed values cast silently back to string on existing tables (#82973); assert post-call DB state for any bulk/schema API, never just the 200 (#82273).
- **SQL sources**: introspection fixtures under a restricted role (privilege-filtered catalogs must answer "undetermined", not "no key" — #84740), engine-variant catalogs (Redshift has no `pg_matviews` — #84705), composite-key column order asserted explicitly.

**Source fixtures from production, not imagination.**
For a deployed source, opt-in sample capture writes scrubbed request/response pairs to S3:

```sh
python manage.py warehouse_sources_capture_http_samples enable --source-type <type> --response-code '*' --limit 50 --ttl 1h
```

(gRPC variant: `warehouse_sources_capture_grpc_samples`.)
Replayed as fixtures, these are the cheapest way to stop tests re-asserting the author's model — the Checkout.com zero-row tables existed precisely because fixtures contained ids the live API never sends (#82961).

## Record the verdict, gate the release

- The PR's **"How did you test this code?"** section is the eval report: which tiers ran, which credential instance (plan/scopes/key type — never secrets), and the claims ledger entries still unverified. An explicit "Not verified" list is the house convention — keep it, it seeds the next person's Tier 1.
- **Unverified tables ship defensive**: `releaseStatus=ReleaseStatus.ALPHA`, `should_sync_default=False` for tables whose shape, volume, or gating is unconfirmed, and conservative parse/merge semantics. That's the posture, not a waiver — pair it with the self-driving handoff above.
- **The ratchet**: every defect this evaluation finds — and every one that still escapes, including via a Self-driving inbox report that traces back to source code — adds a Tier 3 fixture reproducing it and, where expressible, an invariant query detecting it. Add the entry to [references/defect-catalog.md](references/defect-catalog.md) so the catalog stays the institutional memory it is.

## Related skills

- `implementing-warehouse-sources` — building the thing this skill evaluates; its "API behavior verification checklist" is the authoring-time subset of Tier 0.
- `auditing-warehouse-source-coverage` — endpoint gaps rather than correctness; also documents the internal-replica ranking used by the fleet watch.
- `triaging-warehouse-sync-tickets` — a specific customer's failing sync in production.
- `documenting-warehouse-sources` — scopes, key types, and plan gates discovered during Tier 1 belong in the public source doc.
- `signals-scout-data-warehouse` (canonical: `products/signals/skills/signals-scout-data-warehouse/SKILL.md`) — Self-driving's continuous per-project import-integrity watch; the post-merge tier delegates to it via scout notes. `authoring-scouts` covers the note mechanics, and permanent new fleet signatures learned here belong in that scout's skill, not just this one.
