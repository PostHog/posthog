# DRIFTS.md — intentional divergences from PostHog/code

This directory is a point-in-time import of the PostHog/code repository. This file is the
contract for resyncing it: everything listed here is an intentional change made to fit the
monorepo; anything else that differs from the source at the pinned SHA is drift and should
be treated as a bug in the sync.

- Source: https://github.com/PostHog/code
- Pinned SHA: `ca29c39e5e2efbba10d1dcea2741f0037cc95183` (main)
- Imported: 2026-07-20; resynced: 2026-07-24

## Resync protocol (for a human or an agent)

1. Pick the new pinned SHA on PostHog/code main.
2. Replace the `products/desktop/` tree with `git archive <sha> | tar -x -C products/desktop/`, then delete
   `products/desktop/.github` (workflows live at the monorepo root, transformed per the rules below).
   `products/desktop/DRIFTS.md` (this file) is monorepo-only: restore it and update the pinned SHA.
3. Re-derive each `.github/workflows/desktop-*.yml` from its source workflow (mapping table
   below) by applying the transform rules. If a source workflow changed, re-apply the rules
   to the new version rather than hand-merging the diff.
4. New workflows in the source: apply the rules, add them to the mapping table. Removed
   ones: delete the port, move the row to the dropped table.
5. Verify: `actionlint` on every desktop workflow; `pnpm install --frozen-lockfile` and
   `pnpm typecheck` from `products/desktop/`; the monorepo root `pnpm install` must be byte-identical
   before and after (desktop is a nested workspace, not a root workspace member).

## Tree drift inside products/desktop/

The tree is a verbatim copy of the source at the pinned SHA except:

- `.github/` is not imported (see workflow mapping below).
- `DRIFTS.md` (this file) and `docs/plan.md` (the migration plan) exist only in the
  monorepo; restore both on a resync.
- Monorepo symlink convention (enforced by CI): every AGENTS.md needs a sibling CLAUDE.md
  symlink, and CLAUDE.md files must BE symlinks. Applied:
  `packages/ui/src/features/inbox/CLAUDE.md` renamed to `AGENTS.md` plus a symlink, and
  symlinks added in `packages/ui/src/features/{browser-tabs,canvas}/`. Upstream these to
  PostHog/code so resyncs do not reintroduce the violations.

The nested workspace is intentional: `products/desktop/` keeps its own `pnpm-workspace.yaml`,
lockfile, Biome config and Node 22, and is NOT in the root `pnpm-workspace.yaml` globs.
Overrides, catalogs and engines conflict with the root workspace; unification is a later,
separate project.

## Root-repo changes (outside products/desktop/)

- `pnpm-workspace.yaml`: `'!products/desktop'` exclusion. The tree lives under
  `products/` like every other product, but it is a nested standalone workspace and the
  root install must not absorb its package.json (root catalog/overrides would break it).
- `.github/workflows/ci-frontend.yml`, `ci-storybook.yml`, `ci-backend.yml` (and its
  mirror `.depot/workflows/ci-backend.yml`, which CI requires to change in lockstep):
  `!products/desktop/**` added to their `products/**` change filters, so desktop PRs do
  not drag the frontend/storybook/Django suites (desktop has its own desktop-* CI).
- `pyproject.toml`: `products/desktop` in `[tool.ruff]` exclude and in the `[tool.mypy]`
  exclude regex (both run repo-wide with `.`).
- `package.json`: `lint:css` gains `--ignore-pattern "products/desktop/**"` (stylelint's
  glob is `(frontend|products)/**`).
- `.github/workflows/desktop-*.yml`: ported workflows (mapping below).
- `.github/scripts/products/desktop/`: scripts the ported workflows need that lived in the source
  repo's `.github/scripts/`.
- `.oxlintrc.json`: `"desktop"` added to `ignorePatterns` (root `lint:js` runs repo-wide;
  desktop code is Biome-linted by its own workflow).
- `.oxfmtrc.json`: `"desktop"` added to `ignorePatterns` (the frontend CI formats
  `**/*.{md,mdx,yaml,yml}` repo-wide; desktop keeps Biome formatting).
- `.config/.markdownlint-cli2.jsonc`: `"products/desktop/**"` added to `ignores`.
- `.github/workflows/ci-security.yaml`: `--exclude "desktop"` on every semgrep invocation.
  Semgrep found real issues in desktop code that its own CI never checked for — see
  follow-ups.

## Workflow mapping

| Source (.github/workflows/) | Port | Notes beyond the standard transforms |
| --- | --- | --- |
| build.yml | desktop-build.yml | gating: merge_group + `Desktop Build Pass` |
| warm-caches.yml | desktop-warm-caches.yml | seeds every cache the restore-only desktop PR workflows use; pnpm-store caching is explicit (`desktop-pnpm-*` keys) instead of setup-node auto-cache so PR restores share the namespace |
| agent-release-verify.yml | desktop-agent-release-verify.yml | restore-only pnpm store |
| typecheck.yml | desktop-typecheck.yml | gating: merge_group + `Desktop Typecheck Pass` |
| code-quality.yml | desktop-quality.yml | gating: merge_group + `Desktop Quality Pass` |
| test.yml | desktop-test.yml | gating: merge_group + `Desktop Tests Pass`; live-gateway e2e kept with `POSTHOG_CODE_E2E_*` org secrets |
| code-storybook.yml | desktop-storybook.yml | gating: merge_group + `Desktop Storybook Pass`; VR CLI checkout still pulls `PostHog/posthog` master (same repo now, but master's CLI, not the PR branch's, is the intended version) |
| code-build-test.yml | desktop-build-test.yml | |
| code-release.yml | desktop-release.yml | tags `desktop-v*`; legacy publishing to PostHog/code releases kept (see below) |
| code-tag.yml | desktop-tag.yml | computes and pushes `desktop-v*` tags; quiet-period check and patch count scoped `-- products/desktop/` (monorepo master always has fresh commits; unscoped counts would be meaningless) |
| code-update-e2e.yml | desktop-update-e2e.yml | nightly + dispatch; the source's temporary push trigger for `test/macos-auto-update-e2e` is dropped (code-repo branch, and default-only triggers exempt its caches from the cache-write lint) |
| cleanup-draft-releases.yml | desktop-cleanup-draft-releases.yml | targets PostHog/code explicitly via the releaser app token: `github.repository` is now the monorepo, whose drafts belong to other products |
| agent-release.yml | desktop-agent-release.yml | sandbox rebuild dispatch is now same-repo with `actions: write` (cross-repo GH app retired) |
| agent-tag.yml | desktop-agent-tag.yml | agent tags stay `agent-v*`; patch count scoped `-- products/desktop/packages/agent` (unscoped would count every monorepo commit) |
| mobile-build.yml | desktop-mobile-build.yml | |
| mobile-promote.yml | desktop-mobile-promote.yml | |
| pr-build-installer.yml | desktop-pr-build-installer.yml | |
| react-doctor.yml | desktop-react-doctor.yml | comment script moved to `.github/scripts/products/desktop/`; changed-files list filtered to `products/desktop/` so mixed PRs don't get posthog frontend files scanned; sticky-comment marker renamed `desktop-react-doctor:summary` to avoid colliding with a future monorepo react-doctor |

Dropped (the monorepo already provides the function):

| Source | Reason |
| --- | --- |
| codeql.yml | monorepo `ci-security.yaml` covers the repo |
| stale.yml | monorepo `stale.yaml` |
| trunk-impacted-targets.yml | code repo's Trunk merge queue does not carry over; desktop inherits the monorepo queue |
| pr-approval-agent.yml | monorepo runs its own `pr-approval-agent.yml` on all PRs |
| code-discord-release.yml | desktop releases are published on PostHog/code (legacy feed), where the original workflow remains active; a monorepo port would fire for every other product's releases and never for desktop's |

## Transform rules

These are the "monorepo standards" applied to every ported workflow. A resync re-derives
ports from source using these rules.

1. **Filename and name**: `X.yml` -> `desktop-X.yml`, collapsing a `code-` prefix; the
   `name:` field gets a `Desktop` prefix.
2. **Branches**: every `main` reference becomes `master` (the monorepo default branch).
3. **Concurrency**: groups prefixed `desktop-` so they cannot collide with monorepo groups.
4. **Working directory**: jobs that check out the repo get job-level
   `defaults.run.working-directory: desktop`. Never workflow-level (jobs without a checkout
   would fail on the missing directory), and never on jobs whose first run step precedes
   the checkout — those get explicit `products/desktop/` prefixes in run steps instead.
5. **Action inputs are repo-root relative** (`defaults` does not apply to `with:`):
   artifact/cache/junit/sparse-checkout paths get a `products/desktop/` prefix;
   `hashFiles('pnpm-lock.yaml')` -> `hashFiles('products/desktop/pnpm-lock.yaml')`;
   pnpm/action-setup gets `package_json_file: products/desktop/package.json`; setup-node with pnpm
   cache gets `cache-dependency-path: products/desktop/pnpm-lock.yaml`.
6. **Change filters**: the source repo's exclude-only dorny/paths-filter filters match
   every monorepo file, so each filter gains a positive `products/desktop/**` scope and its excludes
   are reanchored under `products/desktop/` (`predicate-quantifier: every` retained). Non-gating
   workflows get top-level `paths: ["products/desktop/**", <own workflow file>]` filters instead.
7. **Merge queue**: gating workflows (build, typecheck, quality, test, storybook) add a
   `merge_group:` trigger, skip all jobs on merge_group runs, and end in an always-running
   `Desktop <X> Pass` collation job — the job to register as the required status check.
   Paths-filtered workflows without `merge_group:` would leave the queue waiting on a check
   that never reports.
8. **Tags**: app release tags are `desktop-v*` in the monorepo (the AWS release role trusts
   `repo:PostHog/posthog:ref:refs/tags/desktop-v*`). Tag triggers, version extraction, tag
   globs and created tags all use the namespace. Agent tags stay `agent-v*`. Releases
   created **on PostHog/code** (legacy update feed) keep bare `v` names.
9. **Same-repo simplifications**: the agent-release sandbox image rebuild dispatches
   `cd-sandbox-base-image.yml` with the ambient `GITHUB_TOKEN` (`actions: write`) instead
   of the retired cross-repo GitHub App.
10. **Untouched on purpose**: pinned action SHAs, secrets names, runner labels and
    `--repo PostHog/code` release publishing.
11. **Monorepo workflow lint** (`hogli lint:workflows`, enforced by CI; run it locally
    after a resync):
    - every job declares `timeout-minutes`;
    - `fetch-depth: 0` checkouts add `filter: blob:none`;
    - no cache write may land on a non-default branch ref. Branch-triggerable desktop
      workflows are restore-only (`actions/cache/restore`; setup-node's `cache: pnpm`
      replaced with an explicit `desktop-pnpm-*` store restore); every cache is seeded by
      `desktop-warm-caches.yml` on master pushes, mirroring the source repo's
      warm-caches.yml design. Rare-run workflows (build-test, mobile-promote) drop
      caching instead.
12. **Gating workflows also trigger on `push: [master]`** (paths-scoped to desktop): house
    pattern and post-merge safety net. The changes-filter step is skipped on push and its
    outputs default to `'true'`, except `packages` (so the live-gateway e2e stays
    PR-only).
13. **Version pins that must track the source tree**: desktop-quality pins the Biome
    version to desktop's `@biomejs/biome` devDependency (setup-biome would otherwise
    resolve a version at the repo root and reject the config).

## Intentional references still pointing at PostHog/code

- `desktop-release.yml` creates and publishes GitHub releases on PostHog/code: every
  install built before the update feed moves to S3 polls that repo's releases. Publishing
  a release there auto-creates a bare `v*` tag at the old repo's frozen main; harmless,
  feed-only. This dual-publish retires once app-version telemetry shows the old feed is
  quiet. PostHog/code#3490 (S3 feed) simplifies this on its next resync into this import.
- `desktop-cleanup-draft-releases.yml` cleans PostHog/code draft releases for the same
  reason.
- `products/desktop/apps/code/package.json` `repository` fields and in-repo docs still reference
  PostHog/code; cosmetic, fixed opportunistically.

## Not done in this PR (follow-ups)

- **Secrets/vars**: the ported workflows expect these to exist in PostHog/posthog (repo or
  org scope): Apple signing (`APPLE_*`, `CSC_*`), `VITE_POSTHOG_API_KEY`,
  `VITE_POSTHOG_API_HOST`, `POSTHOG_SOURCEMAP_API_KEY`, `POSTHOG_ENV_ID`, `POSTHOG_HOST`,
  `GH_APP_ARRAY_RELEASER_*`, `AWS_TWIG_APP_ASSETS_*`, `AWS_DESKTOP_APP_RELEASES_ROLE_ARN`,
  `POSTHOG_CODE_E2E_*` (secret + vars), `TRUNK_API_TOKEN`, Discord webhook, App Store
  Connect (mobile). Until they exist, the corresponding workflows red on this PR — that is
  the dry run telling us which are missing.
- **Required checks**: register `Desktop Build Pass`, `Desktop Typecheck Pass`,
  `Desktop Quality Pass`, `Desktop Tests Pass` (and optionally `Desktop Storybook Pass`)
  as required status checks once this merges.
- **Base tag**: create `desktop-v<X>.<Y>.0` continuing the code repo's version sequence,
  or the tag workflow has no base to count from.
- **npm trusted publisher** for `@posthog/agent`: re-register as posthog/posthog +
  `desktop-agent-release.yml`.
- **Backend test coupling**: add `products/desktop/packages/{agent,shared,git}/**` to
  `ci-backend.yml`'s paths filter (Django's tasks tests exercise the agent overlay), and
  point `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` (products/tasks `local_packages.py`) at the
  in-repo `products/desktop/` for local dev.
- **hogli**: add a `desktop` category (`desktop:dev` etc.) to `hogli.yaml`.
- **Semgrep findings to fix upstream in PostHog/code** (found when semgrep first scanned
  this code; desktop is excluded from semgrep until they are fixed):
  `apps/code/src/main/utils/encryption.ts` uses GCM `createDecipheriv` without an
  explicit auth tag length; `packages/ui/src/features/canvas/freeform/FreeformCanvas.tsx`
  posts messages with a `"*"` target origin.
- **Visual Review baseline**: the first storybook run submits all snapshots as new and
  reds until the run is approved in the VR UI (this repo registration has no desktop
  baseline yet).
