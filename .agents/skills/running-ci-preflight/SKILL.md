---
name: running-ci-preflight
description: >
  Catch the deterministic CI failures reachable from your diff before pushing, with `hogli ci:preflight`.
  Use before a push or before reporting a task done — after editing Python, serializers, migrations,
  workflows, or dependency manifests — to avoid burning a CI matrix on a failure you could catch locally
  (formatting, lint, broken lockfile, OpenAPI drift, migration conflict, stale branch).
  Trigger terms: ci:preflight, preflight, pre-push checks, "will this break CI", catch CI failures locally.
---

# Running ci:preflight before you push

`hogli ci:preflight` scopes a curated set of checks to the files your branch touched — each mapped to a
CI failure class that has taken master down — plus an always-on branch-freshness check. It is the
pre-push counterpart to `hogli ci:insights` (what is _already_ broken on master). Run it as part of your
definition of done.

## The loop

```sh
hogli ci:preflight --fix
```

1. Run with `--fix` — it formats, lints, and auto-fixes what is safe.
2. Read each line: `✓ pass`, `✗ fail`, `→ advisory` (do it yourself), `· skipped` (capability absent).
3. Resolve every `✗ fail` — these are what `--fix` could not (real lint error, broken lockfile, migration conflict). Don't push past them.
4. Act on every `→ advisory` — e.g. `openapi` advisory → run `hogli build:openapi` and commit the drift; `staleness` advisory → `git merge origin/master`.
5. Re-run until clean, then push.

## Notes

- **Advisory by default.** A clean exit means "nothing left to fix", not "CI will pass" — CI stays the authoritative gate. Use `--strict` only in a hook/script that should fail on findings.
- **Staleness.** Flags a branch far behind master (commits ≈ PRs merged) or unsynced for too long; merge master in early so generated-file drift and workflow changes don't break your PR at merge time. Advisory only — never auto-merged.
- **`· skipped (needs stack/node)`** is expected on a bare checkout or sandbox. Start the stack with `hogli start` to run those (OpenAPI, migrations, lockfile), or let CI cover them.
- **Flags.** `--against <ref>` diffs against an explicit base; `--json` emits a machine-readable summary.
- **Kill switch.** `HOGLI_PREFLIGHT_DISABLED=1` makes the command a no-op (exit 0). It is a rollout/emergency lever — respect it; never unset it to force a run.

## Why it matters

Drafts already run a trimmed CI subset; the expensive waste is a ready PR that fails the full matrix on
something deterministic, gets fixed, and re-runs the whole matrix. Catching that locally is the cheapest
CI saving available.
