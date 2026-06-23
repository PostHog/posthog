---
name: running-ci-preflight
description: >
  Catch the deterministic CI failures reachable from your diff before pushing, using `hogli ci:preflight`.
  Use before pushing a branch or telling the human a task is done, after editing Python, serializers,
  migrations, workflows, or dependency manifests, or whenever you want to avoid burning a CI matrix on a
  failure you could have caught locally (formatting, lint, broken lockfile, OpenAPI drift, migration conflict).
  Trigger terms: ci:preflight, preflight, pre-push checks, "will this break CI", catch CI failures locally.
---

# Running ci:preflight before you push

`hogli ci:preflight` scopes a curated set of checks to the files your branch touched and maps each to a
CI failure class that has taken master down. It is the pre-push counterpart to `hogli ci:insights`
(which reports what is *already* broken on master).

Run it as part of your definition of done — before a push, and before reporting a task complete.

## The loop

```sh
hogli ci:preflight --fix     # auto-remediate what's safe, report the rest
```

1. Run with `--fix`. It formats, lints, and fixes what it safely can.
2. Read the report. Each line is `[check] failure-class · detail`, with status `✓ pass`, `✗ fail`,
   `→ advisory` (guidance only — usually needs the dev stack), or `· skipped` (a capability is absent).
3. Fix every `✗ fail` yourself — the remaining failures are the ones `--fix` could not resolve
   (genuine lint errors, a broken lockfile, a real migration conflict). Do not push past them.
4. Act on `→ advisory` lines too: e.g. if `openapi` is advisory, run `hogli build:openapi` and commit the drift.
5. Re-run until it is clean, then push.

## Reading the output

- It is **advisory by default** — a clean exit does not mean "passed", it means "nothing left to fix".
  Use `--strict` only when wiring it into a hook or script that should fail on findings.
- `· skipped (needs stack/node)` is expected on a bare checkout or in a sandbox. Those checks
  (OpenAPI, migrations, lockfile) run on a machine with the dev stack or `node_modules` present —
  start the stack with `hogli start` if you need them, or let CI cover them.
- `--against <ref>` diffs against an explicit base instead of the branch default; `--json` emits a
  machine-readable summary for scripting.

## Why this matters

Drafts already run a trimmed CI subset; the expensive waste is a **ready PR that fails the full matrix
on something deterministic, gets fixed, and re-runs the full matrix.** Catching those locally is the
cheapest CI saving available. Preflight never replaces CI — CI stays the authoritative gate — it just
stops you from being the one who turns master red.
