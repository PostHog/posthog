# MIGRATION.md — intentional divergences from PostHog/code

This directory is a point-in-time import of the PostHog/code repository. This file is the
contract for resyncing it: everything listed here is an intentional change made to fit the
monorepo; anything else that differs from the source at the pinned SHA is drift and should
be treated as a bug in the sync.

- Source: https://github.com/PostHog/code
- Pinned SHA: `fc991d3eea2d1ac649e2502c0197b0fda9b19f58` (main)
- Imported: 2026-07-20; resynced: 2026-08-01

## Resync protocol (for a human or an agent)

1. Pick the new pinned SHA on PostHog/code main.
2. Replace the `products/desktop/` tree with `git archive <sha> | tar -x -C products/desktop/`, then delete
   `products/desktop/.github` (workflows live at the monorepo root, transformed per the rules below).
   `products/desktop/MIGRATION.md` (this file) is monorepo-only: restore it and update the pinned SHA.
   Restore `products/desktop/product.yaml` and `products/desktop/POST-MIGRATION.md` too (see
   the drift list below).
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
- `.stamphog/` is not imported: it is the policy for the source repo's stamphog PR-approval
  merge gate, whose workflow is dropped here (the monorepo runs its own pr-approval-agent
  on all PRs). Delete it on resync.
- `MIGRATION.md` (this file), `POST-MIGRATION.md` (the post-merge runbook) and
  `docs/plan.md` (the migration plan) exist only in the monorepo; restore all three on a
  resync.
- `product.yaml` is monorepo-only and must be restored on a resync. It declares
  `owners: [team-posthog-code]` for the distributed ownership resolver, which drives
  reviewer auto-assignment, `team/` labels and Slack routing to `#team-desktop`. Losing it
  silently makes the whole tree resolve as unowned. It is not a merge gate (that is the
  `.github/CODEOWNERS` entry) and `hogli product:lint` does not pick the directory up, so
  it carries no product-scaffold obligations.
- Monorepo symlink convention (enforced by CI): every AGENTS.md needs a sibling CLAUDE.md
  symlink, and CLAUDE.md files must BE symlinks. Applied:
  `packages/ui/src/features/inbox/CLAUDE.md` renamed to `AGENTS.md` plus a symlink, and
  symlinks added in `packages/ui/src/features/{browser-tabs,canvas}/`. Upstream these to
  PostHog/code so resyncs do not reintroduce the violations.
- `docs/testing.md`: the "Storybook Visual Regression" CI paragraphs are replaced with a
  note that the storybook CI was removed post-merge (see `POST-MIGRATION.md` step 6). The
  source still documents its own storybook workflow; reapply on resync.
- Local security patches (reapply on resync until the pin includes the upstream fix):
  `apps/code/src/main/utils/encryption.ts` passes `{ authTagLength: 16 }` to
  `createDecipheriv` (semgrep `gcm-no-tag-length`, ERROR). For the simple-git 3.36 RCE fix,
  `packages/git/package.json` bumps `simple-git` to `^3.36.0` (the source is on `^3.30.0`,
  so the nested lockfile diverges there too), `packages/git/src/client.ts` opts into
  `unsafe.{allowUnsafeFsMonitor,allowUnsafeEditor,allowUnsafePager}` (3.36's block-unsafe
  plugin otherwise rejects the hardcoded core.fsmonitor perf flag and inherited
  GIT_EDITOR/PAGER), and `packages/git/src/queries.ts` runs `git worktree list` through raw
  `execFile` instead of simple-git. The upstream attempt (PostHog/code#4030) was closed
  unmerged, so these stay local patches; restoring the four files from the previous
  monorepo commit and refreshing the nested lockfile is the reapply.

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
  dorny applies excludes globally (`included && !excludes.some`), so this one exclude
  covers even the broad `**/*.yml` / `**/*.md` rules. ci-frontend's `frontend` filter also
  excludes the desktop CI files that live outside the tree (`!.github/workflows/desktop-*.yml`,
  `!.github/actions/desktop-*/**`, `!.github/scripts/desktop/**`) so desktop-CI-only PRs
  skip the frontend suite. The import PR itself still runs these suites because it edits the
  shared config they watch (ci-frontend.yml, ci-backend.yml, package.json); that is one-time.
- `pyproject.toml`: `products/desktop` in `[tool.ruff]` exclude and in the `[tool.mypy]`
  exclude regex (both run repo-wide with `.`).
- `package.json`: `lint:css` gains `--ignore-pattern "products/desktop/**"` (stylelint's
  glob is `(frontend|products)/**`).
- `frontend/jest.config.ts`: `/products/desktop/` added to `testPathIgnorePatterns`. The
  root Jest roots include `../products`, so it would otherwise collect desktop's `*.test.ts`
  files and fail resolving their workspace-only deps (e.g. `@agentclientprotocol/sdk`).
  Desktop tests run under Vitest in desktop-* CI.
- `.dockerignore`: `products/desktop` added. The file is `*` plus `!products`, so without this
  the whole tree (~56 MiB of icons, fonts, videos, wasm grammars and a vendored ripgrep binary)
  lands in every server image build context. Nothing in the images imports it.
- `pytest.ini`: `--ignore=products/desktop` added to `addopts`. Same reason for the Django
  suite: posthog pytest would otherwise collect desktop's Python tooling tests.
- `.github/workflows/desktop-*.yml`: ported workflows (mapping below).
- `.github/scripts/products/desktop/`: scripts the ported workflows need that lived in the source
  repo's `.github/scripts/`.
- `.oxlintrc.json`: `"desktop"` added to `ignorePatterns` (root `lint:js` runs repo-wide;
  desktop code is Biome-linted by its own workflow).
- `.oxfmtrc.json`: `"desktop"` added to `ignorePatterns` (the frontend CI formats
  `**/*.{md,mdx,yaml,yml}` repo-wide; desktop keeps Biome formatting).
- `.config/.markdownlint-cli2.jsonc`: `"products/desktop/**"` added to `ignores`.
- `.github/workflows/ci-security.yaml` (monorepo-native, not resynced): security scanning
  for the import. Convention-only jobs still exclude `products/desktop` because imported code
  does not follow the monorepo's custom rules (`semgrep-python`'s `.semgrep/rules/security`
  hits 1 finding, `semgrep-devex` hits 206). The dead excludes on jobs that never scanned
  `products/` (`semgrep-js`, `semgrep-general`, `semgrep-go`, `semgrep-rust`) and the clean
  one (`semgrep-products-frontend`) were removed. A new `semgrep-desktop` job gives the tree
  real static security coverage from the universal registry packs (p/javascript, p/python,
  owasp-top-ten, security-audit, trailofbits) at ERROR severity, gated on `products/desktop/**`
  and wired into the `Semgrep Checks Pass` aggregate.

## Workflow mapping

| Source (.github/workflows/) | Port | Notes beyond the standard transforms |
| --- | --- | --- |
| _(none — monorepo-native)_ | desktop-ci.yml | single `pull_request:`/`merge_group:` dispatch that calls the four gating workflows; see transform rule 7 |
| build.yml | desktop-build.yml | gating: `workflow_call` child of desktop-ci.yml + `Desktop Build Pass` |
| warm-caches.yml | desktop-warm-caches.yml | seeds every cache the restore-only desktop PR workflows use; pnpm-store caching is explicit (`desktop-pnpm-*` keys) instead of setup-node auto-cache so PR restores share the namespace |
| agent-release-verify.yml | desktop-agent-release-verify.yml | restore-only pnpm store |
| typecheck.yml | desktop-typecheck.yml | gating: `workflow_call` child of desktop-ci.yml + `Desktop Typecheck Pass` |
| code-quality.yml | desktop-quality.yml | gating: `workflow_call` child of desktop-ci.yml + `Desktop Quality Pass` |
| test.yml | desktop-test.yml | gating: `workflow_call` child of desktop-ci.yml + `Desktop Tests Pass`; live-gateway e2e kept with `POSTHOG_CODE_E2E_*` org secrets |
| code-storybook.yml | _(not ported)_ | removed post-merge: the code-signed VR baseline flagged every story as new from this repo (see the Visual Review baseline note). Do not re-port on resync unless VR is re-registered against posthog/posthog first |
| code-build-test.yml | desktop-build-test.yml | `workflow_dispatch` only; the source's `refactor/electron-vite` push trigger is a code-repo branch and is dropped |
| code-release.yml | desktop-release.yml | tags `desktop-v*`; legacy publishing to PostHog/code releases kept (see below) |
| code-tag.yml | desktop-tag.yml | computes and pushes `desktop-v*` tags; quiet-period check and patch count scoped `-- products/desktop/` (monorepo master always has fresh commits; unscoped counts would be meaningless) |
| code-update-e2e.yml | desktop-update-e2e.yml | nightly + dispatch; the source's temporary push trigger for `test/macos-auto-update-e2e` is dropped (code-repo branch, and default-only triggers exempt its caches from the cache-write lint) |
| cleanup-draft-releases.yml | desktop-cleanup-draft-releases.yml | targets PostHog/code explicitly via the releaser app token: `github.repository` is now the monorepo, whose drafts belong to other products |
| agent-release.yml | desktop-agent-release.yml | sandbox rebuild dispatch is now same-repo with `actions: write` (cross-repo GH app retired) |
| agent-tag.yml | desktop-agent-tag.yml | agent tags stay `agent-v*`; patch count scoped `-- products/desktop/packages/agent` (unscoped would count every monorepo commit) |
| mobile-build.yml | desktop-mobile-build.yml | |
| mobile-promote.yml | desktop-mobile-promote.yml | |
| pr-build-installer.yml | desktop-pr-build-installer.yml | |

Dropped (the monorepo already provides the function):

| Source | Reason |
| --- | --- |
| codeql.yml | monorepo `ci-security.yaml` covers the repo |
| react-doctor.yml | intentionally not imported for now; re-add on a later resync if desktop wants it in the monorepo |
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
7. **Merge queue**: gating workflows (build, typecheck, quality, test) become
   `workflow_call` reusable workflows with no triggers of their own beyond the `push:` master
   arm, and end in an always-running `Desktop <X> Pass` collation job. They are dispatched by
   `desktop-ci.yml` (monorepo-native, no source counterpart), which owns the `pull_request:`
   and `merge_group:` triggers, the PR concurrency group, and the secrets each child declares.
   That keeps the whole suite to one workflow run per PR event instead of four, against
   GitHub's 500-runs/10s dispatch cap.
   Two consequences worth knowing before registering required checks:
   - The check context is `<caller job id> / Desktop <X> Pass` (for example
     `build / Desktop Build Pass`), not the bare job name. Register those strings.
   - Neither the parent nor the children may take a trigger-level `paths:` filter; a required
     check that never dispatches leaves the PR stuck waiting for status. Change detection
     stays in each child's internal `changes` job.
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
    - jobs that sign or publish release artifacts restore no dependency cache at all:
      every `actions/setup-node` in `desktop-release.yml` and `desktop-agent-release.yml`
      passes `package-manager-cache: false` instead of `cache: 'pnpm'`. A poisoned cache
      entry would otherwise reach a signing job (zizmor `cache-poisoning`). Reapply on
      resync: the source workflows cache there.
12. **Gating workflows also trigger on `push: [master]`** (paths-scoped to desktop): house
    pattern and post-merge safety net. The changes-filter step is skipped on push and its
    outputs default to `'true'`, except `packages` (so the live-gateway e2e stays
    PR-only).
13. **Version pins that must track the source tree**: desktop-quality pins the Biome
    version to desktop's `@biomejs/biome` devDependency (setup-biome would otherwise
    resolve a version at the repo root and reject the config).
14. **Required-check gate form** (`hogli` WF007): each `Desktop * Pass` collator uses
    `if: always()` and tests every `needs:` dependency (the `changes` detector included)
    as `!= "success" && != "skipped"`, then `exit 1`. The source repo's `== "failure"`
    form and the `merge_group` early-exit are dropped: on `merge_group` the deps skip and
    the allowlist guards pass. `desktop-pr-build-installer.yml`'s `comment` job posts a PR
    comment rather than gating, so it carries a `# hogli-lint: not-a-required-gate` opt-out
    above the job key.
15. **Desktop-scoped secret names**: the source repo owns its whole secret namespace, so
    some of its bare names mean something different (or nothing) in the monorepo. The three
    sourcemap-upload secrets are renamed with a `DESKTOP_` prefix on the `secrets.` lookup
    only; the env var handed to the build keeps its original name, because the app reads it:
    `POSTHOG_ENV_ID: ${{ secrets.DESKTOP_POSTHOG_ENV_ID }}`. Applies to
    `POSTHOG_SOURCEMAP_API_KEY`, `POSTHOG_ENV_ID` and `POSTHOG_HOST` across desktop-release,
    desktop-build-test, desktop-pr-build-installer and desktop-update-e2e. Left bare:
    `VITE_POSTHOG_API_KEY` and `VITE_POSTHOG_API_HOST` (already org-wide and shared), names
    that already carry a desktop, twig or code qualifier (`AWS_DESKTOP_*`, `AWS_TWIG_*`,
    `POSTHOG_CODE_E2E_*`) and genuinely repo-wide ones (`TRUNK_API_TOKEN`, `VR_API_TOKEN`,
    `GH_APP_POSTHOG_PATHS_FILTER_*`). Reapply on resync: the source uses the bare names.

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

Everything that has to happen once this merges is sequenced in
[`POST-MIGRATION.md`](./POST-MIGRATION.md). The entries below are the same work seen from
the PR's side; that file is the one to follow on merge day.

- **Secrets/vars**: the ported workflows expect these to exist in PostHog/posthog (repo or
  org scope): Apple signing (`APPLE_*`, `CSC_*`), `VITE_POSTHOG_API_KEY`,
  `VITE_POSTHOG_API_HOST`, `DESKTOP_POSTHOG_SOURCEMAP_API_KEY`,
  `DESKTOP_POSTHOG_ENV_ID`, `DESKTOP_POSTHOG_HOST` (see transform rule 15),
  `GH_APP_ARRAY_RELEASER_*`, `AWS_TWIG_APP_ASSETS_*`, `AWS_DESKTOP_APP_RELEASES_ROLE_ARN`,
  `POSTHOG_CODE_E2E_*` (secret + vars), `TRUNK_API_TOKEN`, Discord webhook, App Store
  Connect (mobile). Until they exist, the corresponding workflows red on this PR — that is
  the dry run telling us which are missing.
- **Required checks**: register `Desktop Build Pass`, `Desktop Typecheck Pass`,
  `Desktop Quality Pass` and `Desktop Tests Pass` as required status checks once this
  merges.
- **Base tag**: create `desktop-v<X>.<Y>.0`, or the tag workflow has no base to count from.
  Use the next unused minor above the code repo's latest release, not the minor it is
  currently on: the patch counter restarts from the new tag, so reusing that minor emits a
  version that already exists on the legacy feed. See `POST-MIGRATION.md` step 2.
- **npm trusted publisher** for `@posthog/agent`: re-register as posthog/posthog +
  `desktop-agent-release.yml`.
- **Backend test coupling**: add `products/desktop/packages/{agent,shared,git}/**` to
  `ci-backend.yml`'s paths filter (Django's tasks tests exercise the agent overlay), and
  point `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` (products/tasks `local_packages.py`) at the
  in-repo `products/desktop/` for local dev.
- **hogli**: add a `desktop` category (`desktop:dev` etc.) to `hogli.yaml`.
- **Semgrep coverage**: desktop now gets universal static security coverage from the
  `semgrep-desktop` job (see root-repo changes). The one ERROR finding it caught,
  `gcm-no-tag-length` in `apps/code/src/main/utils/encryption.ts`, is fixed (local patch,
  upstreamed). Remaining WARNING-level items are informational and not gated:
  `packages/ui/src/features/canvas/freeform/FreeformCanvas.tsx` posts to a `"*"` target
  origin, which is required for its opaque-origin sandboxed srcDoc iframe.
- **Dependency CVEs (local patch, reapply on resync until the pin includes the upstream
  fix)**: `pnpm-workspace.yaml` overrides pin advisory-flagged packages to patched,
  age-compliant versions (protobufjs 7.6.5, axios 1.18.1, hono 4.12.28, @xmldom/xmldom
  0.8.13, node-forge 1.4.0, simple-git 3.36.0, drizzle-orm 0.45.2, fast-uri 3.1.4,
  @hono/node-server 1.19.13, lodash 4.18.0, serialize-javascript 7.0.5, undici 8.5.0/7.28.0,
  rollup 4.59.0, brace-expansion 1.1.16/2.1.2, ws 7.5.11/8.21.0, path-to-regexp@8 8.4.2,
  qs 6.15.3, smol-toml 1.6.1), plus direct floors
  `simple-git ^3.36.0` and `tar ^7.5.19`; the lockfile is regenerated to match. This mirrors
  PostHog/code hardening PR #4030. `path-to-regexp` is range-scoped to `@8` because a 6.3.0
  line is also in the tree and a blanket override would force it across a major. To
  regenerate under the 7-day `minimumReleaseAge`,
  temporarily add `@expo-google-fonts/material-symbols` to `minimumReleaseAgeExclude` (an
  already-committed too-new transitive that blocks re-resolution), run
  `pnpm install --lockfile-only`, then revert that one exclude. simple-git 3.36 (RCE fix)
  needs the `packages/git/src/{client.ts,queries.ts}` source patches below. The agent sub-package ships its own publish lockfile (`packages/agent/pnpm-lock.yaml`); patch it by
  adding `@modelcontextprotocol/sdk` 1.29.0, `@isaacs/brace-expansion` 5.0.1, `path-to-regexp` 8.4.2,
  `fast-uri` 3.1.4, `@hono/node-server` 1.19.13, `qs` 6.15.3 as overrides in a temp
  `packages/agent/pnpm-workspace.yaml` (copy the catalog +
  age-exclude the `@earendil-works/pi-*` deps and `@expo-google-fonts/material-symbols`), strip the
  `workspace:*` devDeps from a temp package.json, `pnpm install --lockfile-only`, then restore.
  This file is byte-identical to PostHog/code's `packages/agent/pnpm-lock.yaml`; regenerate once
  and copy rather than generating it twice. The remaining
  transitive high/moderate tail (minimatch, picomatch, js-yaml, form-data, svgo, etc.) is
  left for a dedicated dependency-hygiene sweep.
- **Visual Review baseline**: the committed `apps/code/snapshots.yml` is signed for the
  PostHog/code VR registration, so submitting from this repo flags every story as new and
  the job reds. In-app approval can't fix it (the VR bot can't commit a posthog-signed
  baseline onto the PR branch, and each resync re-imports the file from code and
  overwrites it). After the merge the storybook CI was removed outright rather than kept
  behind the `desktop-skip-vr` label gate: `desktop-storybook.yml`, its `storybook` job in
  `desktop-ci.yml` and the Playwright cache warming in `desktop-warm-caches.yml` are gone.
  Do not re-port `code-storybook.yml` on a resync; `POST-MIGRATION.md` step 6 covers how
  to bring it back once VR is re-registered against posthog/posthog.
