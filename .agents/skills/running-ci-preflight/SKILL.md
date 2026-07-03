---
name: running-ci-preflight
description: >
  Catch the deterministic CI failures reachable from your diff before pushing, with `hogli ci:preflight`.
  Use when the pre-push hook blocks a push, before reporting a task done, or after editing Python,
  serializers, migrations, workflows, or dependency manifests — to avoid burning a CI matrix on a failure
  you could catch locally (formatting, lint, broken lockfiles, OpenAPI drift, migration conflict, stale branch).
  Trigger terms: ci:preflight, preflight, pre-push checks, pre-push hook failed, "will this break CI".
---

# Running ci:preflight

`hogli ci:preflight` scopes a curated set of checks to the files your branch touched — each mapped to a
CI failure class that has taken master down — plus an always-on branch-freshness check. It is the
pre-push counterpart to `hogli ci:insights` (what is _already_ broken on master).

The pre-push hook runs `ci:preflight --strict` automatically and blocks the push on failed checks.
**Never bypass it with `--no-verify`** — fix what it reports instead.

## The loop (when the hook blocks, or before reporting done)

```sh
hogli ci:preflight --fix
```

1. Run with `--fix` — it formats, lints, and auto-fixes what is safe.
2. Read each line: `✓ pass`, `✗ fail`, `→ advisory` (do it yourself), `· skipped` (capability absent).
3. Resolve every `✗ fail` — these are what `--fix` could not (real lint error, broken lockfile, migration conflict). These block the push.
4. Act on every `→ advisory` — e.g. `openapi` advisory → run `hogli build:openapi` and commit the drift; `staleness` advisory → `git merge origin/master`. Advisories never block, but ignoring them ships the failure to CI.
5. Re-run until clean, then push.

## Notes

- **Strict = failures only.** `--strict` (what the hook runs) exits non-zero only on `✗ fail` — advisories are unverifiable-locally classes, so they warn without blocking. A clean exit means "nothing left to fix", not "CI will pass" — CI stays the authoritative gate.
- **Staleness is risk-based.** It fires when merging master _now_ would actually break something — textual merge conflicts (computed via `git merge-tree`, working tree untouched), migrations added on both sides, generated-file inputs changed on both sides, or CI workflows changed on master — plus a behind/age backstop, aggressive by default (5 commits / 2 days; env-tunable via `HOGLI_PREFLIGHT_STALE_COMMITS`/`HOGLI_PREFLIGHT_STALE_DAYS`) so we over-warn to start and tune down from telemetry. Merge master in when it fires. Advisory only, never auto-merged.
- **`· skipped (needs stack/node)`** is expected on a bare checkout or sandbox. Start the stack with `hogli start` to run those, or let CI cover them. No hooks in your environment (no `node_modules`)? Run the loop yourself before pushing.
- **Flags.** `--against <ref>` diffs against an explicit base; `--json` emits a machine-readable summary.
- **Kill switch.** `HOGLI_PREFLIGHT_DISABLED=1` makes the command (and the hook) a no-op with exit 0. It is a rollout/emergency lever — respect it; never unset it to force a run.

## Why it matters

Drafts already run a trimmed CI subset; the expensive waste is a ready PR that fails the full matrix on
something deterministic, gets fixed, and re-runs the whole matrix. Catching that locally is the cheapest
CI saving available.
