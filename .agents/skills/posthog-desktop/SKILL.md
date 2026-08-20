---
name: posthog-desktop
description: >
  Scopes work to the desktop app at products/desktop — a nested standalone pnpm/turbo/Biome
  workspace imported from PostHog/code, not part of the root frontend or Django build. Use when
  the user says /posthog-desktop, or works on the Electron desktop app, apps/code, apps/web,
  apps/mobile, packages/core, packages/ui, packages/workspace-server, @posthog/api-client,
  @posthog/agent, or the agent framework. Pins the working directory to products/desktop, swaps
  in that tree's toolchain and conventions in place of the monorepo's, and defines the few paths
  outside the tree that may be touched (Django APIs the app calls, desktop-* CI at the root).
---

# Working in products/desktop

`products/desktop/` is the PostHog desktop app (Electron + agent framework), imported from
PostHog/code and kept as a **nested standalone workspace**: own `pnpm-workspace.yaml`, own
lockfile, own Biome config, Node 22. It is excluded from the root `pnpm-workspace.yaml`, from
ruff/mypy, from root Jest, from oxlint/oxfmt, from stylelint and from pytest.

**Read [`products/desktop/AGENTS.md`](../../../products/desktop/AGENTS.md) before writing code
in this tree.** It is the source of truth for architecture, layer boundaries, DI, and style.
This skill only covers the scoping contract around it.

## Scope contract

Default: **everything you read, edit, run and test lives under `products/desktop/`.** Run all
commands with that as cwd. Do not go fishing in `frontend/`, `posthog/`, or other `products/*`
for patterns — the desktop tree has its own, and copying monorepo idioms in is a defect.

Step outside only when one of these is true:

1. **The user explicitly tells you to.**
2. **A backend API the app calls needs to change.** The client is
   `packages/api-client/`; the endpoints it hits live in the Django monorepo (see below).
3. **Desktop CI / config that lives at the root by design.** The list is fixed:
   `.github/workflows/desktop-*.yml`, `.github/actions/desktop-*/`,
   `.github/scripts/desktop/`, and the exclusion entries in `pnpm-workspace.yaml`,
   `pyproject.toml`, `pytest.ini`, `package.json` (`lint:css`), `frontend/jest.config.ts`,
   `.dockerignore`, `.oxlintrc.json`, `.oxfmtrc.json`, `.config/.markdownlint-cli2.jsonc`,
   `.github/workflows/ci-{frontend,storybook,backend}.yml` (+ `.depot/workflows/ci-backend.yml`).
   Touch these only to keep an exclusion correct; say so when you do.

Anything else outside the tree: stop and ask.

## Toolchain — root CLAUDE.md does not apply here

| Root monorepo says                                    | In products/desktop use                                       |
| ----------------------------------------------------- | ------------------------------------------------------------- |
| `ruff` / `mypy` / pytest                              | nothing — no Python app code here                             |
| oxlint + Oxfmt, `pnpm --filter=@posthog/frontend fix` | `pnpm lint` (Biome check --write), `pnpm format`              |
| Jest, `hogli test`                                    | Vitest (`pnpm test`), Playwright (`pnpm test:e2e`)            |
| `pnpm --filter=@posthog/frontend typescript:check`    | `pnpm typecheck` (turbo, all packages)                        |
| Kea logics, `typegen:write`                           | Zustand stores + InversifyJS services; no kea, no typegen     |
| LemonUI in `frontend/` and `products/*/frontend/`     | `@posthog/quill` + Tailwind + Radix Themes                    |
| `hogli build:openapi` → generated frontend types      | `packages/api-client/src/generated.ts` (hand-maintained here) |
| 4-space / repo Prettier habits                        | Biome, 2-space, double quotes                                 |

Commands (from `products/desktop/`): `pnpm install`, `pnpm dev`, `pnpm build`, `pnpm typecheck`,
`pnpm lint`, `pnpm test`, `pnpm test:e2e`, `pnpm --filter <pkg> <task>`,
`node scripts/check-host-boundaries.mjs`.

Never run root-level `pnpm install` expecting it to cover desktop, and never let a desktop
dependency change alter the root lockfile — the root install must stay byte-identical.

## Cross-boundary: the Django API

`packages/api-client/` calls monorepo endpoints — tasks (`/api/projects/:id/tasks/...`),
signals, agent applications, environments/MCP installations, `/api/users/`. When a change needs
the backend:

- Read the Django side to get the contract right; that is in scope without asking.
- **Editing** it is a separate, monorepo-side change: root CLAUDE.md rules apply again
  (`/improving-drf-endpoints`, `/django-migrations`, serializer `help_text`, `hogli build:openapi`).
- Keep the two sides in one PR only if they must ship together; otherwise land the backend first.
- Wiring the app at a local Django instance (OAuth app, RSA keys, flags) is
  `products/desktop/docs/LOCAL-DEVELOPMENT.md`.

## Provenance

The tree was imported from the standalone PostHog/code repo, which is now archived. There is
no resync process: the monorepo copy is the only maintained one, and fixes land here like any
other monorepo change. `product.yaml` declares ownership (`team-posthog-code`) for reviewer
auto-assignment and Slack routing; do not delete it.

## Desktop-local skills

`products/desktop/.claude/skills/` ships its own: `test-electron-app` (drive the running app
over CDP `:9222`), `quill-code`, `storybook-stories`, `onboarding-videos`.
Prefer these over monorepo equivalents while in this tree.

## Before reporting done

- `pnpm typecheck` and `pnpm lint` from `products/desktop/`, plus `pnpm test` for touched packages.
- After touching `packages/core`: `biome lint packages/core`, zero `noRestrictedImports`.
- After touching `@posthog/platform`: rebuild or typecheck its `dist/`.
- After moving logic out of `apps/code`: `node scripts/check-host-boundaries.mjs --prune`.
- Confirm the diff touches nothing outside `products/desktop/` — or name what it touches and why.
