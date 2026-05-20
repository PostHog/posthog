---
name: run-posthog
description: Start, inspect, and drive the PostHog dev stack. Use for /run and /verify on this repo — when asked to launch PostHog, check whether the stack is healthy, inspect a running process, or verify a UI change against the live app.
---

PostHog is Django + Vite + Celery + plugin-server, backed by Postgres, ClickHouse, Kafka, Redis, and Temporal in Docker, fronted by an Envoy-style proxy at `http://localhost:8010`. The dev stack runs in detached mode under `phrocs` so the running processes are inspectable from this session via the `phrocs` MCP server. Browser MCP servers (`chrome-devtools-mcp`, `playwright`) drive the UI; nothing about this skill ships its own driver.

All paths below are relative to the repo root.

## Prerequisites

- **flox** 1.12+ provisions the toolchain — `curl -L https://downloads.flox.dev/by-env/stable/install.sh | sudo bash`
- **Docker** — OrbStack preferred on macOS (`brew install --cask orbstack`)
- **1Password CLI** (optional) — `brew install 1password-cli`, only if `.env.local` contains `op://` refs

## Launch

```bash
hogli dev:setup          # first time only — interactive wizard picks which workers to run
hogli up -d -y           # start the stack detached under phrocs
hogli services:ready -y  # wait for Docker services (Postgres, CH, Kafka, Redis)
hogli wait -y            # wait for phrocs-managed units (Django, Vite, Celery, plugin-server)
hogli doctor             # optional: stale migrations, zombie phrocs, disk pressure
```

First boot is 60-90s while Django imports and Vite warms. Stop with `hogli down -y` (leaves Docker services running for fast restart).

## Is the stack healthy?

```bash
curl -sf http://localhost:8010/_health                                                         # 200
curl -sf -o /dev/null -w '%{http_code}' http://localhost:8010/                                 # 200 or 302
curl -sS http://localhost:8010/api/projects/@current | grep -q '"code":"not_authenticated"'   # API + DB reachable
```

For richer detail, use the `phrocs` MCP server — it reports per-process status without any scripting:

- `mcp__phrocs__get_process_status` (no args) — all units, with `ready`, `exit_code`, memory, CPU.
- `mcp__phrocs__get_process_status process="frontend"` — single unit (or `backend`, `capture`, `celery-worker`, `ingestion`, `nodejs`, ...).
- `mcp__phrocs__get_process_logs process="backend"` — tail recent stdout/stderr.
- `mcp__phrocs__toggle_process process="celery-worker"` — restart a single unit without bouncing the whole stack.

A healthy stack reports `status:"running"` and `ready:true` for `backend`, `frontend`, `capture`, `celery-worker`, `ingestion`, `nodejs`. `migrate-*` units should be `done` with `exit_code:0`.

## Drive the UI for /verify

Every empty PostHog scene looks broken because no events exist. To verify a UI change, you need a workspace with realistic data. The canonical path is the same one the Playwright suite uses: `POST /api/setup_test/organization_with_team/`. Gated on `DEBUG=True | E2E_TESTING | CI | TEST`, all of which local dev satisfies via `DEBUG=True`. Implementation: `posthog/api/playwright_setup.py` + `posthog/test/playwright_setup_functions.py:create_organization_with_team` — 3 clusters via `HedgeboxMatrix`, ~5-10s end to end. Reference call site: `playwright/utils/playwright-setup.ts:251`.

Avoid `hogli dev:demo-data` for /run and /verify — it calls `generate_demo_data` with `n_clusters=500` (default at `posthog/management/commands/generate_demo_data.py:59`) and takes 5-30 minutes. It exists for humans who want a big realistic dataset to play with; it's the wrong tool for automated launch-and-screenshot.

The full browser-MCP recipe:

1. `new_page` `http://localhost:8010/login`.
2. `evaluate_script` the workspace bootstrap. Per-call email so reruns don't collide; password fixed at `12345678`; response gives back the team_id and a personal API key.

   ```js
   const r = await fetch('/api/setup_test/organization_with_team/', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ data: { skip_onboarding: true } }),
   })
   const { result } = await r.json()
   // result: { user_email, team_id, personal_api_key, organization_id, ... }
   return result
   ```

3. `evaluate_script` the in-page login. Runs in the page context so Django's CSRF middleware sees the right cookies (`playwright/utils/playwright-setup.ts:282-291`).

   ```js
   const r = await fetch('/api/login/', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ email: workspace.user_email, password: '12345678' }),
   })
   return r.status // 200 = logged in; 403 = you're not in-page; 400 = workspace setup didn't actually create the user
   ```

4. `navigate_page` to `http://localhost:8010/project/{team_id}{scene-path}`.
5. `wait_for` text or a `[data-attr]` element. PostHog attaches `data-attr` to virtually every rendered element; use it as the "page hydrated" signal. `networkidle` and `load` never settle because PostHog.js and Vite HMR keep polling.
6. `take_screenshot`. The accessibility snapshot from `wait_for` is also enough on its own for most "is this element present?" verifications — no pixel comparison needed.

For API-only calls (creating fixtures, hitting endpoints without a browser), use the `personal_api_key` from the setup_test response as `Authorization: Bearer <key>` — no login dance.

For deeper interaction (clicking, filling forms, inspecting console), the same MCP toolkit (`chrome-devtools-mcp:*` / `playwright:*`) covers it. No project-specific wrapper needed.

## For /verify: diff → URL mapping

The frontend uses kea-router. The mapping rule:

| Edited path                              | Scene URL (under `/project/{team_id}/`)                 |
| ---------------------------------------- | ------------------------------------------------------- |
| `frontend/src/scenes/<name>/**`          | usually `/<name>` (e.g. `insights/` → `/insights`)      |
| `frontend/src/scenes/activity/**`        | `/activity/explore` (and other `ActivityTab`s)          |
| `frontend/src/scenes/data-management/**` | `/data-management/<sub>`                                |
| `frontend/src/scenes/settings/**`        | `/settings/<section>`                                   |
| `frontend/src/scenes/authentication/**`  | `/login`, `/signup`, `/preflight` (un-scoped)           |
| `products/<name>/frontend/**`            | per the `urls:` block in `products/<name>/manifest.tsx` |
| `frontend/src/layout/**`                 | renders everywhere; verify on any scene                 |
| `frontend/src/lib/components/<X>.tsx`    | grep usages, screenshot the scene that mounts it        |

Canonical sources to grep when the path isn't obvious:

- `frontend/src/scenes/urls.ts` — top-level URL helpers (`urls.insights()`, `urls.dashboard(...)`, etc.).
- `frontend/src/scenes/scenes.ts` — scene-to-route registry.
- `products/<name>/manifest.tsx` — per-product routes.

## Gotchas

- **`migrate-clickhouse` often crashes on first launch — this is the hard prereq for `setup_test`.** `mcp__phrocs__get_process_status process="migrate-clickhouse"` may show `status:"crashed" exit_code:1` — if so, the `posthog.person` ClickHouse table doesn't exist, and `/api/setup_test/organization_with_team/` returns 500 `Table posthog.person does not exist`. This applies even with `no_demo_data: true` — User/Team creation triggers a CH-writing signal regardless of the demo-data flag, so there is no "skip CH" escape hatch. HogQL-backed scenes (insights, dashboards, web analytics) also break with "Unknown table expression identifier 'events'". Fix: `hogli migrations:run`. If that fails on async-migration `is_required()`, you need `hogli dev:reset` (which wipes Docker volumes — destructive). On a stack that already has corrupted CH replica state in ZooKeeper, even `dev:reset` may be required. UI scenes that don't query CH (login, home, settings, feature flags) render fine without any of this.
- **`hogli wait` exits 0 even when phrocs is unreachable.** Don't trust its return code as ground truth — confirm with `mcp__phrocs__get_process_status` or the `curl` probes.
- **Vite serves on `:8234`, not the URL you browse.** You browse `http://localhost:8010` (the Envoy-style proxy). The proxy reverse-proxies Vite for `/static/*` and Django for everything else. Hitting `:8234/` directly returns 404 because Vite has no index route at the dev-server root.
- **Worktrees share Docker containers but compete for ports.** All worktrees on the same machine resolve to the same `posthog-clickhouse-1` / `posthog-db-1` containers, so DB state is global. But ports 8000/8010/8234 can only be held by one worktree at a time — kill the granian/vite/phrocs of the other worktree before `hogli up -d` here.
- **CSP warnings and 401s in the browser console are normal pre-auth.** The preflight/login page tries to fetch `/api/projects/@current`, `/api/users/@me/`, and PostHog.js remote config — all 401 until you sign up. WASM/CSP "Report Only" warnings come from the dev CSP.
- **Direct `curl -X POST /api/login/` returns 403 (CSRF).** Session login must run in-page via `browser_evaluate` so cookies and CSRF tokens flow. For non-browser API calls, use the `personal_api_key` from the `setup_test` response as `Authorization: Bearer <key>` — no CSRF on token auth.
- **`.env.local` may use 1Password refs.** Without `op` installed, refs become literal strings (e.g. `OPENAI_API_KEY=op://...`) and downstream services fail with cryptic auth errors. Install `op` or replace with literals.

## Troubleshooting

- **`hogli up -d` exits with `Another instance of bin/start is already running`** — previous run still active or crashed without cleanup. `mcp__phrocs__get_process_status` shows what's there; if nothing's running, `rm bin/start.lock` and retry.
- **`docker info` fails with `dial unix /Users/<you>/.orbstack/run/docker.sock: ... no such file`** — OrbStack is stopped. `open -a OrbStack`.
- **`/api/projects/@current` returns 500 instead of 401** — Postgres or ClickHouse unreachable. `docker ps | grep posthog-` and look for unhealthy containers; `hogli services:ready` waits for all of them.
- **`POST /api/login/` returns 400 `invalid_credentials`** — you're logging in as a user the `setup_test` workspace didn't actually create (CH crash usually). Check the response of the setup_test call; if it 500'd, fix CH first (see the `migrate-clickhouse` gotcha).
- **`POST /api/setup_test/organization_with_team/` returns 404** — `DEBUG`, `E2E_TESTING`, `CI`, and `TEST` are all false. Local dev has `DEBUG=True` by default; if it's not set, `.env.local` is missing or `DJANGO_SETTINGS_MODULE` points at a prod-like settings module.
- **`POST /api/setup_test/organization_with_team/` returns 500 `Table posthog.person does not exist`** — `migrate-clickhouse` crashed during boot. See the gotcha above.
- **In-page `fetch('/api/login/')` returns 403** — you're calling it from outside the page context (e.g. `page.request.post` rather than `page.evaluate`). Use `evaluate_script` / `browser_evaluate` so the call originates in-page.
