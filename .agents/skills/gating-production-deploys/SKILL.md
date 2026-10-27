---
name: gating-production-deploys
description: >
  Use when adding or editing a GitHub Actions workflow that pushes a container
  image to a registry (ECR/ghcr/Docker Hub via build-push-action) or dispatches a
  production deploy (a `commit_state_update` repository_dispatch to PostHog/charts).
  Also use for adding an ordered image release for a new worker or a new consumer
  of the shared image.
  Those run from a single canonical deploy repo, gated by the CD_DEPLOY_ENABLED
  variable. Does NOT apply to workflows that publish GitHub releases, npm, crates,
  or Homebrew — those stay on the public repo.
---

# Gating production builds and deploys

Container-image pushes and Charts deploy dispatches run from one canonical deploy
repo, selected by the `CD_DEPLOY_ENABLED` variable. Gate every such step or it
publishes/deploys from the wrong place.

**Gate** these when they run on `push`-to-`master` / `schedule` / `workflow_dispatch`:

- a prod-tag container image push, and
- a `commit_state_update` dispatch to `PostHog/charts` (plus its deployer-token step).

**Don't gate:**

- Release/distribution workflows — GitHub release, npm, crate, Homebrew (e.g.
  `build-phrocs.yml`, `release-cli.yml`). They publish from public; leave them.
- `pull_request` validation builds (gating them breaks contributor CI).
- change-detection / setup jobs (use the org check only, not the variable).

The test is "pushes a prod image or triggers a deploy" — not "builds on master".

## The gate

```yaml
if: github.repository_owner == 'PostHog' && vars.CD_DEPLOY_ENABLED == 'true'
```

Use this instead of hardcoding `github.repository == 'PostHog/posthog'`.

## Patterns

```yaml
# whole job is the deploy/push (no PR builds) — gate the job:
if: github.repository_owner == 'PostHog' && vars.CD_DEPLOY_ENABLED == 'true'

# deploy job/step already keyed to master — add the gate:
if: github.repository_owner == 'PostHog' && vars.CD_DEPLOY_ENABLED == 'true' && github.ref == 'refs/heads/master'

# build job that also serves PRs — gate only the master arm of its `if`:
(github.event_name == 'push' && github.ref == 'refs/heads/master' && needs.changes.outputs.files == 'true'
  && github.repository_owner == 'PostHog' && vars.CD_DEPLOY_ENABLED == 'true')

# push step, master-only:
push: ${{ github.ref == 'refs/heads/master' && vars.CD_DEPLOY_ENABLED == 'true' }}
# push step, `push: true` (also pushes on PR for validation):
push: ${{ github.event_name == 'pull_request' || vars.CD_DEPLOY_ENABLED == 'true' }}

# reusable that pushes — add a `push` boolean input (default true), pass from caller:
#   with: { push: ${{ github.event_name == 'pull_request' || vars.CD_DEPLOY_ENABLED == 'true' }} }
```

Set `CD_DEPLOY_ENABLED` on the repo that should ship **before** merging, or master
pushes skip the build/deploy. Lint with `actionlint`.

Examples: `container-images-cd.yml` (whole-job); `cd-mcp-image.yml`,
`livestream-docker-image.yml`, `cd-sandbox-base-image.yml` (mixed PR+master);
`rust-docker-build.yml` + `_rust-build-images.yml` (reusable `push` input).
Counter-example, not gated: `build-phrocs.yml`.

## New ordered-image publishers and shared builds

For a new monorepo publisher or independent releases of a shared built image,
read [Ordered image releases](references/ordered-image-releases.md). Reuse the
repository helper and canonical policy. Use `.github/actions/shared-image-releases`
for `inspect` and `publish`. The legacy paths-filter action owns manifest loading
and projection. Selective channels compare each destination frontier with the
successful build and publish only eligible digests. Keep channels empty until
their infrastructure, policy entry, seed and consumer binding have separate
activation review. Services built elsewhere retain their existing
publisher family.

The publisher validates source policy offline, then authenticates with the
selective role and checks origin access through the frontier lookup. It copies
once to the US origin and verifies its digest; ECR handles replication. Adding
another worker needs its infrastructure entry and policy entry, with no workflow
edit. A receipt proves the origin, not regional availability.

For new-service onboarding or an existing-service migration, hand the consumer's
source identity, policy and destination coordinates to the Charts migration
helper. Charts checks resolved regional repositories against source policy and
provisioned infrastructure, together with owner, lane, image group and inherited
Git filters. Kargo checks regional tag, revision and digest agreement. Obtain
that check before treating the consumer setup as ready.
