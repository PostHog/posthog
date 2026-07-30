# Desktop migration plan

Moving PostHog/code into this monorepo as `products/desktop/`. This document is the plan
and running status; `../DRIFTS.md` is the mechanical contract for regenerating the import.

## Decisions

- **Target path**: `products/desktop/`, alongside the other products. The folder also
  contains `apps/web`, `apps/mobile`, `apps/cli` and the npm-published agent packages,
  not just the Electron app.
- **Squash import, no history.** The old repo stays locked but never deleted: pre-import
  history, blame and issue redirects live there permanently.
- **Nested standalone workspace first.** `products/desktop/` keeps its own
  `pnpm-workspace.yaml`, lockfile, Biome config and Node 22, excluded from the root
  workspace globs. Root overrides, catalogs and engines conflict; unification is phase 2,
  after the move settles (root workspace membership, named catalog, override
  reconciliation, `@posthog/quill` via `workspace:*`, Node alignment).
- **Update feed moves to S3 before the repo moves** (PostHog/code#3490). electron-updater's
  GitHub provider resolves updates through the repo-global `/releases/latest` pointer, so
  a monorepo releases page can never be an update feed. The generic-provider S3 feed
  removes the old repo as a release host; GitHub releases on PostHog/code stay
  dual-published until app-version telemetry shows the legacy feed is quiet.
- **Release tags are `desktop-v*`** (agent tags stay `agent-v*`). The AWS release role
  trusts `repo:PostHog/posthog:ref:refs/tags/desktop-v*` for feed-bucket writes.
- **`@posthog/agent` stays inside the nested workspace** (`packages/agent`): its bundled
  deps (`@posthog/shared`, `@posthog/git`, `@posthog/enricher`) are workspace members the
  desktop app also consumes via `workspace:*`. Publishing hardens to the SDK release
  process (changesets + approval-gated environment, `release-cli.yml` is the in-repo
  reference) as part of the move, replacing unattended publish-on-merge.

## Status

Done:

- S3 feed infra (posthog-cloud-infra#9385): buckets and tag-scoped OIDC roles.
- PostHog/code#3490 (merged): generic-provider feed at `desktop-releases.posthog.com`
  (private bucket behind CloudFront), channel files as the atomic publish flip,
  `releases.json` powering in-app release notes. Verified end to end: tag-scoped OIDC
  writes, the server-side copy flip and public reads through the product domain.
- Dry-run import PR (PostHog/posthog#72483): full tree staged, 17 workflows ported or
  accounted for, DRIFTS.md resync contract, desktop CI green inside the monorepo
  (including the merge-queue aggregator pattern) except two admin-gated items below.

Blocked on admin actions:

- Scope the `POSTHOG_CODE_E2E_*` gateway org secret/vars to PostHog/posthog (the live
  e2e's fail-loud guard reds until then).
- Approve the initial Visual Review storybook baseline for this repo.

## Remaining phases

1. **Land #3490 in PostHog/code**, verify a real release end to end (feed objects, an old
   install auto-updating onto the S3-polling build, release notes in the app), then let
   the fleet drain onto the S3 feed while dual-publishing continues.
2. **Regenerate the import from newer pinned SHAs** as PostHog/code keeps moving (protocol
   in DRIFTS.md). The first resync after #3490 picks up the S3 release workflow.
3. **People-side prep**: copy the secrets inventory into posthog (signing, sourcemaps,
   releaser app, AWS, Trunk, Discord, App Store Connect), re-register the npm trusted
   publisher for `@posthog/agent`, create the `desktop-v<X>.<Y>.0` base tag, register the
   `Desktop * Pass` required checks, create the `product/code` area label for issue
   transfer.
4. **Cutover** (hard cut at a final pinned SHA): lock old main, land the final import
   through the merge queue, bulk-transfer open issues (`gh issue transfer` keeps comments
   and leaves redirects), comment the patch-port script on remaining open PRs
   (`git diff main...BRANCH | git apply -p1 --directory=products/desktop`), keep
   dual-publishing releases.
5. **After**: backend test coupling (add `products/desktop/packages/{agent,shared,git}/**`
   to the tasks filters in ci-backend; point `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` at the
   in-repo tree), hogli `desktop:*` commands, sparse-checkout recipe in the README, agent
   release hardening, fix the semgrep findings DRIFTS lists, retire the legacy GitHub feed
   once telemetry allows, then archive PostHog/code.

## The consumer matrix (why backend coupling matters)

`@posthog/agent` and the agent-server wire format are consumed by the tasks sandboxes
(`npm install @posthog/agent@latest` in the base image), posthog_ai's backend and frontend
wire-type copies, signals/Scout, and external repos (agent-stack, hogland, aili5).
Pre-merge coverage for the in-repo consumers is the concrete win of the move: agent
changes run the tasks backend tests in the same PR instead of breaking sandboxes after an
npm publish. Golden-fixture contract tests against `@posthog/agent/server/schemas` are the
follow-up that makes wire drift fail loudly in both directions.
