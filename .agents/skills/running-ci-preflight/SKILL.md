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
2. Read each line: `✓ pass`, `✗ fail`, `⚠ warning` (non-blocking finding), `→ advisory` (do it yourself), `· skipped` (capability absent).
3. Resolve every `✗ fail` — these are what `--fix` could not (real lint error, broken lockfile, migration conflict). These block the push.
4. Act on every `→ advisory` — e.g. `openapi` advisory → run `hogli build:openapi` and commit the drift; `staleness` advisory → `git merge origin/master`. Advisories never block, but ignoring them ships the failure to CI. **Resolve them before pushing, including drift you didn't introduce — you own the branch state you push.**
5. Re-run until clean, then push.

## Notes

- **Strict = failures only.** `--strict` (what the hook runs) exits non-zero only on `✗ fail` — advisories are unverifiable-locally classes, so they warn without blocking. A clean exit means "nothing left to fix", not "CI will pass" — CI stays the authoritative gate. Non-blocking is a mechanism limit, not permission to skip.
- **`type-check` is a nudge, not a run.** Only a repo-wide mypy run matches CI (mypy follows imports, so a changed-file subset misses reverse-dependency breakage), and that costs minutes cold — too much to tax every push with. So preflight names the command instead of running it: judge whether your change is type-risky and run it yourself. CI blocks on the same command, so a type error you skip here comes back as a full re-run.
- **`complexity` warns only.** Cyclomatic complexity above 10 in a changed file shows as `⚠ warning` and never blocks; CI annotates the same warning and posts it to the CI report comment. Simplify the function when you next touch it rather than gaming the number.
- **`semgrep-devex` advises on findings your branch introduced.** It scans the changed files and their merge-base copies within one 15-second budget. Both scans use the cached version `SEMGREP_IMAGE` pins in `.github/workflows/ci-security.yaml`, with network access disabled. Run `hogli ci:preflight --prepare-semgrep` once with network access to prepare that tool. A missing tool or an incomplete scan skips with a reason, without delaying the push for downloads. A finding already on master is not reported. CI blocks on a new one, so fix it before you push. The advisory prints the command that shows the rule.
- **`snapshot-baselines` advises when `frontend/snapshots.yml` loses entries for stories your branch did not change.** This is what a bad merge-conflict resolution looks like. When the stories still render, the merge queue fails the batch that carries the file. Run the `git diff` the check prints and restore the entries you did not mean to remove. The entries of a story you deleted, renamed or retitled in the same branch pass.
- **`merge-queue-lane` warns only, and the pre-push hook skips it.** It fires when a few cross-cutting files (a CI workflow, a lane script) make the whole PR claim every merge queue lane, which makes the queue merge in series behind it. Move those files to their own PR when the other changes do not need them.
- **Staleness is risk-based.** It fires when merging master _now_ would actually break something — textual merge conflicts (computed via `git merge-tree`, working tree untouched), migrations added on both sides, generated-file inputs changed on both sides, or CI workflows changed on master — plus a behind/age backstop, aggressive by default (5 commits / 2 days; env-tunable via `HOGLI_PREFLIGHT_STALE_COMMITS`/`HOGLI_PREFLIGHT_STALE_DAYS`) so we over-warn to start and tune down from telemetry. Merge master in when it fires. Advisory only, never auto-merged.
- **`· skipped (needs …)`** is expected on a bare checkout or sandbox. `needs stack`/`needs clickhouse` want a running dev stack (`hogli start`), `needs node` wants `pnpm install`, `needs desktop-node` wants `pnpm --dir products/desktop install` and `needs agent-node` wants `pnpm --dir packages/agent install` (both nested workspaces are excluded from the root install and have their own lockfiles), and `needs python-env` wants `uv sync`, so the synced project environment is the `python` on PATH. Satisfy what you can, or let CI cover the rest. No hooks in your environment (no `node_modules`)? Run the loop yourself before pushing.
- **Flags.** `--against <ref>` diffs against an explicit base; `--json` emits a machine-readable summary.
- **Kill switch.** `HOGLI_PREFLIGHT_DISABLED=1` makes the command (and the hook) a no-op with exit 0. It is a rollout/emergency lever — respect it; never unset it to force a run.

## Why it matters

Drafts already run a trimmed CI subset; the expensive waste is a ready PR that fails the full matrix on
something deterministic, gets fixed, and re-runs the whole matrix. Catching that locally is the cheapest
CI saving available.
