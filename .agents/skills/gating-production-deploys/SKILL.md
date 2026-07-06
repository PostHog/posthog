---
name: gating-production-deploys
description: >
  Use when adding or editing a GitHub Actions workflow that pushes a container
  image to a registry (ECR/ghcr/Docker Hub via build-push-action) or dispatches a
  production deploy (a `commit_state_update` repository_dispatch to PostHog/charts).
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
- `pull_request` / `merge_group` validation builds (gating them breaks contributor CI).
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
push: ${{ github.event_name == 'pull_request' || github.event_name == 'merge_group' || vars.CD_DEPLOY_ENABLED == 'true' }}

# reusable that pushes — add a `push` boolean input (default true), pass from caller:
#   with: { push: ${{ github.event_name == 'pull_request' || vars.CD_DEPLOY_ENABLED == 'true' }} }
```

Set `CD_DEPLOY_ENABLED` on the repo that should ship **before** merging, or master
pushes skip the build/deploy. Lint with `actionlint`.

Examples: `container-images-cd.yml` (whole-job); `cd-mcp-image.yml`,
`livestream-docker-image.yml`, `cd-sandbox-base-image.yml` (mixed PR+master);
`rust-docker-build.yml` + `_rust-build-images.yml` (reusable `push` input).
Counter-example, not gated: `build-phrocs.yml`.
