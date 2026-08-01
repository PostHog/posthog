# Post-migration runbook

Steps to take when the desktop import PR merges into `master`. Ordered: each step assumes
the ones above it are done. `MIGRATION.md` covers the import itself and the resync contract.

This file is monorepo-only. Restore it on a resync (see `MIGRATION.md`).

## Merging

Trunk's merge queue is paused, so `/trunk merge` is a no-op. Squash is the only method the
`master` ruleset allows:

```bash
gh pr merge <number> --squash
```

Branch protection still applies: an approving review, code owner review, the required
status checks and signed commits. Shortly after a force-push GitHub's mergeability cache
can be stale and the first attempt fails with "the base branch policy prohibits the merge";
retrying a moment later works.

## 1. Secrets and vars (before tagging)

The release, signing and mobile workflows read these from PostHog/posthog at repo or org
scope. Add them before step 2, or the first tag produces a failed release:

| Group | Names |
| --- | --- |
| Apple signing | `APPLE_*`, `CSC_*` |
| App telemetry | `VITE_POSTHOG_API_KEY`, `VITE_POSTHOG_API_HOST` |
| Sourcemaps | `DESKTOP_POSTHOG_SOURCEMAP_API_KEY`, `DESKTOP_POSTHOG_ENV_ID`, `DESKTOP_POSTHOG_HOST` |
| Release plumbing | `GH_APP_ARRAY_RELEASER_*`, `AWS_TWIG_APP_ASSETS_*`, `AWS_DESKTOP_APP_RELEASES_ROLE_ARN` |
| E2E | `POSTHOG_CODE_E2E_*` (secret + vars) |
| Other | Discord webhook, App Store Connect (mobile) |

Only the three sourcemap names are prefixed. Their code-repo equivalents are bare
(`POSTHOG_HOST` and so on) and would collide with the monorepo's own secrets, so the ported
workflows read the prefixed name and pass it to the build under the original env var the app
expects:

```yaml
POSTHOG_ENV_ID: ${{ secrets.DESKTOP_POSTHOG_ENV_ID }}
```

The `VITE_POSTHOG_*` pair is already org-wide and shared, so those keep their existing names
and need nothing new.

Copy the values across unchanged; only the secret name differs. Three are worth a second
look rather than a straight copy:

- `DESKTOP_POSTHOG_ENV_ID` is a numeric **project** id despite the name. It feeds the
  `projectId` option of `@posthog/rollup-plugin` (the plugin deprecated `envId` in favour of
  `projectId`). Read it from the project URL, `us.posthog.com/project/<N>/`.
- `DESKTOP_POSTHOG_HOST` is optional. The plugin defaults to `https://us.i.posthog.com`
  when it is unset, and the guard in `apps/code/vite.shared.mts` only requires the API key
  and project id. Note the failure mode: if either of those two is missing the plugin
  returns `null` and the build silently skips sourcemap upload instead of failing, so
  confirm sourcemaps actually landed after the first release.
- `DESKTOP_POSTHOG_SOURCEMAP_API_KEY` is a **personal** API key tied to whoever minted it.
  Mint a fresh one owned by a bot or shared account so it does not break on that person's
  key rotation.

## 2. Create the base version tag

`desktop-tag.yml` derives `MAJOR.MINOR` from the newest tag matching
`desktop-v<major>.<minor>` (a `.0` suffix is allowed) and computes the patch as the number
of commits touching `products/desktop/` since it. With no base tag the job exits 1 with
"No version tag found". It runs on cron at 01:00 and 17:00 UTC, so this breaks within
hours of merge if skipped.

```bash
git tag desktop-v0.59.0 <squash-merge-sha>
git push origin desktop-v0.59.0
```

Tag at or after the merge commit. The import commit itself touches `products/desktop/`, so
tagging before it folds the whole import into the patch count.

**Do not reuse the minor the code repo is on.** The patch counter restarts from the new
tag, so a `desktop-v0.58.0` base yields `0.58.1` on the first release while PostHog/code
has already published far higher in that line (`v0.58.202` as of 2026-08-01). Two failures
follow:

- `desktop-release.yml` publishes to PostHog/code under bare `v` names for the legacy
  update feed. `v0.58.1` already exists there, so the job skips creation, then
  `gh release upload --clobber` overwrites a historical release's assets and
  `gh release edit --draft=false` republishes it.
- It is a downgrade on the live feed. Clients on a higher patch never take it.

Pick the next unused minor above the latest published release at cutover time and confirm
it is free first:

```bash
gh release view v0.59.0 --repo PostHog/code   # expect: release not found
```

Patch numbers advance far more slowly than in the code repo: the count is scoped to
`products/desktop/` and squash-merges collapse each PR to one commit. Monotonic, which is
what the updater needs, but not comparable to the old cadence.

## 3. Disable `code-tag.yml` on PostHog/code

It still runs on the same `0 1,17 * * *` cron. Left enabled, both repos independently bump
the same minor and race to publish to the same release feed.

## 4. Expect the first master-push CI wave

Six desktop workflows trigger on push to `master`: `desktop-warm-caches`,
`desktop-build`, `desktop-typecheck`, `desktop-quality`, `desktop-test`
and `desktop-agent-tag`.

`desktop-warm-caches` seeds every cache the restore-only PR workflows depend on. Until it
finishes, desktop PRs run without a warm pnpm store and are slow. That is expected, not a
regression.

## 5. Register the required status checks

These run and pass today, but nothing enforces them:

- `Desktop Build Pass`
- `Desktop Typecheck Pass`
- `Desktop Quality Pass`
- `Desktop Tests Pass`

## 6. Storybook CI (removed post-merge)

`desktop-storybook.yml` was removed after the merge. The committed `apps/code/snapshots.yml`
is signed for the PostHog/code Visual Review registration, so every submission from this repo
flagged all stories as new and the job could not go green without a full VR re-registration.
The `desktop-skip-vr` label is obsolete and can be deleted. To bring visual regression back,
re-register VR against posthog/posthog first, then restore the workflow (and its `storybook`
job in `desktop-ci.yml` and the Playwright cache warming in `desktop-warm-caches.yml`) from
git history and let the VR bot commit a posthog-signed baseline.

## 7. Re-register the npm trusted publisher

`@posthog/agent` publishes from `desktop-agent-release.yml`. Re-register the trusted
publisher as posthog/posthog + that workflow, or agent releases fail at publish.

## Lower priority

- **Backend test coupling**: add `products/desktop/packages/{agent,shared,git}/**` to
  `ci-backend.yml`'s paths filter (Django's tasks tests exercise the agent overlay), and
  point `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` (products/tasks `local_packages.py`) at the
  in-repo `products/desktop/`.
- **hogli**: add a `desktop` category (`desktop:dev` etc.) to `hogli.yaml`.
- **Dual-publish retirement**: `desktop-release.yml` and `desktop-cleanup-draft-releases.yml`
  still target PostHog/code for the legacy update feed. Retire once app-version telemetry
  shows the old feed is quiet.
- **Dependency tail**: the remaining transitive high/moderate advisories (minimatch,
  picomatch, js-yaml, form-data, svgo) are left for a dedicated dependency-hygiene sweep.
