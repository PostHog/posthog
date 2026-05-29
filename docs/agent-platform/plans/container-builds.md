# Agent platform: container build + deploy plan

## Context

The agent platform now has three production Node services that have stayed
local-only:

- [services/agent-ingress/](../../../services/agent-ingress/) — HTTP entry (chat, webhook, slack, MCP) → enqueues sessions
- [services/agent-runner/](../../../services/agent-runner/) — queue worker that drives sessions through pi-ai + tools
- [services/agent-janitor/](../../../services/agent-janitor/) — authoring HTTP proxy + queue sweep timer

…a migration runner that owns the `AGENT_DB_URL` schema:

- [services/agent-migrations/](../../../services/agent-migrations/) — SQL-only [node-pg-migrate](https://github.com/salsita/node-pg-migrate) runner + the migrations themselves. Run as a one-shot Job (chart hook / init container) before each rollout. Equivalent to the rust `sqlx-migrate` image.

…plus a UI service:

- [services/agent-console/](../../../services/agent-console/) — Next.js authoring console

The deploy runbook ([docs/agent-platform/docs/deploy-runbook.md](../docs/deploy-runbook.md))
already specifies env vars per service, but there is no Dockerfile or CI
workflow producing images. Right now the only agent Dockerfile in tree is
[services/agent-sandbox-host/Dockerfile](../../../services/agent-sandbox-host/Dockerfile)
(a tiny Alpine sidecar with no build step).

Goal: get these services built and pushed on every master commit and PR,
and trigger a charts deploy on master, using the same conventions as
[Dockerfile.node](../../../Dockerfile.node) /
[ci-nodejs-container.yml](../../../.github/workflows/ci-nodejs-container.yml)
and the rust pattern in [.github/rust-images.yml](../../../.github/rust-images.yml).

The three runtime services + the migration runner share Node 24, ESM,
tsx, pg, and (for the services) agent-shared. Their entrypoints are
<50 lines each. They co-evolve (one DB schema, one agent-shared,
migrations land in lockstep with the code that reads them) and the rust
pattern's per-service image matrix is overkill for that. Console is
structurally different (Next.js, Node 20+).

**Recommendation:** ship _two_ images.

1. **`posthog-agents`** — single image, single Dockerfile, four baked-in
   bundles (`ingress.mjs`, `runner.mjs`, `janitor.mjs`, `migrate.mjs`)
   plus the migration SQL files. `CMD` selects which service runs in each
   replica or one-shot job. Modelled on
   [services/mcp/Dockerfile](../../../services/mcp/Dockerfile). Folding
   the migrator in is deliberate: it guarantees `migrate.mjs` and the
   services that read the schema ship as the same SHA, so a rollout is
   "run the migrate Job at SHA X, then roll the services at SHA X."
2. **`posthog-agent-console`** — Next.js standalone build, its own
   Dockerfile.

`agent-sandbox-host` keeps its existing Dockerfile but joins the new CI
workflow so it's built + pushed too (it has no workflow today).

## Approach

### 1. `services/agents/Dockerfile` — one image, four bundles

New top-level Dockerfile at `services/agents/Dockerfile` (the directory is
new — empty other than the Dockerfile, a tiny package.json, the build
script, and a short README explaining the multi-service image). Build
context is the repo root so pnpm can resolve the workspace.

Structure (mirrors [services/mcp/Dockerfile](../../../services/mcp/Dockerfile)):

- `ARG NODE_VERSION=24.13.0` pinned from `.nvmrc`
- **Build stage**
  - `corepack enable`
  - Copy `pnpm-lock.yaml`, `pnpm-workspace.yaml`, root `package.json`,
    root `tsconfig.json`, `patches/`
  - Copy workspace manifests only:
    `services/agent-ingress/package.json`,
    `services/agent-runner/package.json`,
    `services/agent-janitor/package.json`,
    `services/agent-migrations/package.json`,
    `services/agent-shared/package.json`,
    `services/agent-tools/package.json`
  - `pnpm install --frozen-lockfile --filter '@posthog/agent-ingress...' --filter '@posthog/agent-runner...' --filter '@posthog/agent-janitor...' --filter '@posthog/agent-migrations...'`
    with `--mount=type=cache,id=pnpm,target=/pnpm/store`
  - Copy sources for the same six packages
  - Bundle each service entrypoint to a self-contained ESM file via
    esbuild (same approach as
    [services/mcp/scripts/build-hono.ts](../../../services/mcp/scripts/build-hono.ts)).
    Add `services/agents/scripts/build.ts` that takes a service name and
    emits `dist/<service>.mjs`. Run it four times in the build stage —
    once per entrypoint (ingress, runner, janitor, migrate).
- **Runtime stage**
  - `FROM ${NODE_IMAGE}` slim
  - `ARG COMMIT_HASH` → `/code/commit.txt` (matches Dockerfile.node)
  - `COPY --from=build /code/services/agents/dist/ ./dist/` — keep the
    `dist/` directory so `migrate.mjs` can resolve the migrations
    folder a level up (see below).
  - `COPY --from=build /code/services/agent-migrations/migrations/ ./migrations/`
    — raw `.sql` files. `node-pg-migrate` reads them at runtime, they
    do not get bundled.
  - `USER node`, `ENV NODE_ENV=production`
  - **No default CMD with a service name.** The deploy manifest sets
    the command per release:
    - service: `command: ["node", "dist/ingress.mjs"]` / `runner.mjs` / `janitor.mjs`
    - migration job: `command: ["node", "dist/migrate.mjs", "up"]`
  - `EXPOSE 8080 8082` so the same image can serve either HTTP service.

**Migrations layout detail.**
[services/agent-migrations/src/lib.ts](../../../services/agent-migrations/src/lib.ts)
resolves the migrations directory as
`resolve(dirname(import.meta.url), '../migrations')`. After bundling, the
final `migrate.mjs` lives at `/code/dist/migrate.mjs` so the runtime
resolves `/code/migrations` — that's why everything goes under `dist/`
in the image and the SQL files sit one level up. Alternative would be an
env override, but matching the existing path resolution keeps the bundle
behaviour identical to local `tsx src/bin.ts up`.

Why bundle vs ship `node_modules`: matches the mcp pattern — smaller
runtime image, faster cold starts, no install at deploy. Native deps
worth checking before commit: `pg` ships pure-JS by default (no
`pg-native`); `@earendil-works/pi-ai`, `typebox`, and `node-pg-migrate`
are pure JS. No binary deps blocker.

### 2. `services/agent-console/Dockerfile` — Next.js

Separate Dockerfile, standard Next.js multi-stage:

- Build stage: `corepack enable`; install workspace deps with
  `--filter @posthog/agent-console...`; `pnpm --filter @posthog/agent-console run build`
- Runtime stage: copy `.next/standalone` + `.next/static`,
  `CMD ["node", "services/agent-console/server.js"]`, `EXPOSE 3040`
- next.config sets `output: 'standalone'` and pins
  `outputFileTracingRoot` to the monorepo root so the standalone trace
  is deterministic across local + docker builds. Without the pin, Next
  picks a parent directory and the COPY paths drift.
- The console source has no `public/` directory today; if static
  assets get added later, a third `COPY` line needs to land in the
  Dockerfile.

This image is **only** the console UI. Storybook is dev-time only.

### 3. `services/agent-sandbox-host/Dockerfile` — unchanged

Already correct
([services/agent-sandbox-host/Dockerfile](../../../services/agent-sandbox-host/Dockerfile)).
Just needs CI wiring.

### 4. `.dockerignore` updates

Edit root [.dockerignore](../../../.dockerignore) — it's allowlist-style,
so the new paths must be explicitly let through:

```text
!services/agents
!services/agent-ingress
!services/agent-runner
!services/agent-janitor
!services/agent-migrations
!services/agent-shared
!services/agent-tools
!services/agent-console
!services/agent-sandbox-host
services/agent-*/node_modules
services/agent-*/dist
services/agent-*/.next
services/agent-tests
```

(Tests don't need to be in the image; the harness runs in CI/dev only.)

### 5. CI workflow — `.github/workflows/ci-agent-container.yml`

Single workflow with a matrix over the three images. Modelled on
[ci-nodejs-container.yml](../../../.github/workflows/ci-nodejs-container.yml)
but with a small matrix instead of a single image — closer to the rust
shape, lighter than splitting into 3 workflow files.

Triggers / path filter:

```yaml
paths:
  - 'services/agent-*/**'
  - 'services/agents/**'
  - 'pnpm-lock.yaml'
  - 'pnpm-workspace.yaml'
  - '.github/workflows/ci-agent-container.yml'
```

Jobs:

- `changes` — `dorny/paths-filter` like the node workflow, output
  `agent_files`. Master push without changes is still a no-op (saves
  Depot minutes).
- `build` — matrix:

  ```yaml
  matrix:
    include:
      - image: posthog-agents
        dockerfile: services/agents/Dockerfile
        context: .
      - image: posthog-agent-console
        dockerfile: services/agent-console/Dockerfile
        context: .
      - image: posthog-agent-sandbox-host
        dockerfile: services/agent-sandbox-host/Dockerfile
        context: services/agent-sandbox-host
  ```

  Each entry runs:
  - `depot/setup-action`, `docker/setup-buildx-action`,
    `docker/setup-qemu-action`
  - Use the shared
    [./.github/actions/docker-meta](../../../.github/actions/docker-meta/action.yml)
    composite for login (GHCR + ECR) and tag generation. Each image gets
    its own Depot project ID — the workflow ships with
    `REPLACE_WITH_DEPOT_PROJECT_ID` placeholders that must be filled in
    once the three Depot projects are created (same as
    [.github/rust-images.yml](../../../.github/rust-images.yml)). The
    workflow will fail at the depot build step until they're set.
  - `depot/build-push-action` with
    `platforms: linux/arm64,linux/amd64`, `push: true`, `COMMIT_HASH`
    build arg
  - Emit digest to step summary + upload as artifact `digest-<image>`
    (same idiom as the rust reusable workflow)

- `deploy` — only on `push` to `master`. Matrix over the six logical
  releases:

  ```yaml
  matrix:
    include:
      - release: agent-ingress
        image: posthog-agents
      - release: agent-runner
        image: posthog-agents
      - release: agent-janitor
        image: posthog-agents
      - release: agent-migrations
        image: posthog-agents
      - release: agent-console
        image: posthog-agent-console
      - release: agent-sandbox-host
        image: posthog-agent-sandbox-host
  ```

  Four of those releases share the same `posthog-agents` SHA — that's
  the explicit trade-off of the single-image approach, and it's a
  feature for this domain (ingress + runner + janitor + migrations share
  schema and agent-shared, want lockstep). The `agent-migrations`
  release is a one-shot k8s Job, not a Deployment — the chart on the
  other side picks up the new SHA and runs `node dist/migrate.mjs up`
  before the service Deployments roll. Equivalent to how
  `sqlx-migrate` is shipped in
  [rust-docker-build.yml](../../../.github/workflows/rust-docker-build.yml).
  Each dispatches to `PostHog/charts` via
  `peter-evans/repository-dispatch` with the standard `commit_state_update`
  payload, using the deployer GitHub App (same step structure as the
  rust deploy job).

Optional follow-up: a smoke-test workflow analogous to
[rust-smoke-test-build.yml](../../../.github/workflows/rust-smoke-test-build.yml)
that builds without pushing on PRs that don't change
`services/agent-*/**`. Not in scope for v1.

### 6. Charts repo coordination (out of tree, but a deploy step)

This plan only covers what lives in `posthog/posthog`. To actually land
deploys, [PostHog/charts](https://github.com/PostHog/charts) needs:

- A new `agent-ingress` release (chart) that pins `image.sha`, sets
  `command: ["node", "dist/ingress.mjs"]`, mounts `AGENT_BUNDLE_ROOT`,
  reads env from the per-service secret.
- Same shape for `agent-runner` (`dist/runner.mjs`) and `agent-janitor`
  (`dist/janitor.mjs`).
- An `agent-migrations` release as a k8s Job (or chart pre-install /
  pre-upgrade hook) with `command: ["node", "dist/migrate.mjs", "up"]`
  and `AGENT_DB_URL` from the same secret the services use. Must
  complete successfully before the service Deployments roll — same
  ordering as Django's `posthog-migrate` Job vs `posthog` Deployment.
- A separate `agent-console` release.
- An `agent-sandbox-host` release if the runner-side prod sandbox
  pattern requires it. Per
  [deploy-runbook.md](../docs/deploy-runbook.md), ingress/runner/janitor
  are deployable today; prod sandbox topology may use Modal — confirm
  before wiring this release.

Out of scope for this repo's PR, but flag in the description so the
charts PR can land alongside.

## Files to touch

New:

- `services/agents/Dockerfile`
- `services/agents/scripts/build.ts` (esbuild bundling)
- `services/agents/package.json` (tiny — just devDeps for the bundler;
  optional if we inline esbuild via tsx)
- `services/agents/README.md` (1 paragraph explaining multi-service image)
- `services/agent-console/Dockerfile`
- `.github/workflows/ci-agent-container.yml`

Edited:

- [.dockerignore](../../../.dockerignore) — allowlist new service paths,
  ignore `dist/`, `node_modules/`, `agent-tests/`, `.next/`
- `services/agent-console/next.config.*` — add `output: 'standalone'`
  if missing
- [docs/agent-platform/docs/deploy-runbook.md](../docs/deploy-runbook.md)
  — add a "Container images" section linking image refs and noting the
  per-service command

## Verification

Local image builds (pre-push):

```bash
# All four entrypoints in one image
docker build -f services/agents/Dockerfile -t posthog-agents:dev .

# Migrations first (one-shot)
docker run --rm -e AGENT_DB_URL=... posthog-agents:dev node dist/migrate.mjs up

# Long-running services
docker run --rm -e POSTHOG_DB_URL=... -e AGENT_DB_URL=... -p 8080:8080 \
  posthog-agents:dev node dist/ingress.mjs
docker run --rm -e ... posthog-agents:dev node dist/runner.mjs
docker run --rm -e ... -p 8082:8082 posthog-agents:dev node dist/janitor.mjs

# Console
docker build -f services/agent-console/Dockerfile -t posthog-agent-console:dev .
docker run --rm -p 3040:3040 posthog-agent-console:dev
```

E2E smoke (matches [deploy-runbook.md](../docs/deploy-runbook.md) §1–§5):

- `curl $INGRESS/healthz` → 200
- `curl $JANITOR/healthz` → 200
- `curl -H "x-internal-secret: $S" $JANITOR/native_tools` → JSON list
- Fire one chat trigger, watch `/listen` SSE, confirm a session
  reaches `completed`

CI verification:

- Open a PR touching `services/agent-runner/src/index.ts` → the
  `ci-agent-container` workflow runs, all three images build and push
  with PR-tagged refs, no deploy job runs.
- Open a PR adding a file under `services/agent-migrations/migrations/`
  → the same workflow rebuilds `posthog-agents` (the new SQL is copied
  into the image). Verify the new file is present:
  `docker run --rm posthog-agents:pr-N ls migrations`.
- Merge to master → the same workflow runs and the deploy job triggers
  six `commit_state_update` dispatches to `PostHog/charts` (including
  the `agent-migrations` Job).
- Open a PR that doesn't touch `services/agent-*/**` → workflow
  short-circuits via `changes` job.

## Non-goals

- Multi-architecture optimisation beyond what Depot already does.
- A separate Helm chart in this repo (charts live in `PostHog/charts`).
- Migrating `agent-sandbox-host` away from Alpine — its no-deps design
  is the point.
- Bundling `agent-tools` or `agent-shared` as standalone images — they
  are library packages, consumed by the three runtime services.
- Smoke-test PR workflow (follow-up).
