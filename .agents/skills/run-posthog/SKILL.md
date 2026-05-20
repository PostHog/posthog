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

## Get a real test user

The codebase convention everywhere — Playwright suite, management commands, e2e fixtures — is `test@posthog.com` / `12345678`. The user is created by `hogli dev:demo-data` (= `python manage.py generate_demo_data`); `hogli dev:reset` creates it as part of the full bootstrap.

```bash
hogli dev:demo-data   # creates test@posthog.com:12345678 + demo events. Slow (~5 min on first run).
hogli dev:api-key     # creates the stable personal API key phx_dev_local_test_api_key_1234567890abcdef tied to that user
```

If `hogli up -d` is the first thing you've run after a fresh checkout, the test user does NOT exist yet — `POST /api/login/` will return `invalid_credentials` until `dev:demo-data` has run.

## Drive the UI for /verify

The recipe a browser MCP follows to take an authenticated screenshot of a scene:

1. `navigate` to `http://localhost:8010/login`.
2. `evaluate` the in-page login fetch. This is the codebase-canonical pattern from `playwright/utils/playwright-setup.ts:282-291` — running the POST in the page context means Django's CSRF middleware sees the right cookies.

   ```js
   const r = await fetch('/api/login/', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ email: 'test@posthog.com', password: '12345678' }),
   })
   return r.status // 200 = logged in; 400 = bad creds; 403 = CSRF (you're not in-page)
   ```

3. `evaluate` `(await fetch('/api/users/@me/').then(r => r.json())).team.id` to discover the team_id (`1` on a single-user dev stack).
4. `navigate` to `http://localhost:8010/project/{team_id}{scene-path}`.
5. Wait for a `[data-attr]` element — PostHog's test-id convention, attached to virtually every rendered element. Use this as your "page hydrated" signal; `networkidle` and `load` never settle because PostHog.js and Vite HMR keep polling.
6. `screenshot`.

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

- **`migrate-clickhouse` often crashes on first launch.** `mcp__phrocs__get_process_status process="migrate-clickhouse"` may show `status:"crashed" exit_code:1` — if so, ClickHouse migrations didn't fully run, the `posthog.events` table doesn't exist, and `/api/setup_test/...` plus HogQL-backed scenes (insights, dashboards, web analytics) fail with "Unknown table expression identifier 'events'". Fix: `hogli migrations:run`. If that itself fails on async-migration `is_required()`, you need `hogli dev:reset` (which wipes Docker volumes). UI scenes that don't query CH (login, home, settings, feature flags) still render fine.
- **`hogli wait` exits 0 even when phrocs is unreachable.** Don't trust its return code as ground truth — confirm with `mcp__phrocs__get_process_status` or the `curl` probes.
- **Vite serves on `:8234`, not the URL you browse.** You browse `http://localhost:8010` (the Envoy-style proxy). The proxy reverse-proxies Vite for `/static/*` and Django for everything else. Hitting `:8234/` directly returns 404 because Vite has no index route at the dev-server root.
- **Worktrees share Docker containers but compete for ports.** All worktrees on the same machine resolve to the same `posthog-clickhouse-1` / `posthog-db-1` containers, so DB state is global. But ports 8000/8010/8234 can only be held by one worktree at a time — kill the granian/vite/phrocs of the other worktree before `hogli up -d` here.
- **CSP warnings and 401s in the browser console are normal pre-auth.** The preflight/login page tries to fetch `/api/projects/@current`, `/api/users/@me/`, and PostHog.js remote config — all 401 until you sign up. WASM/CSP "Report Only" warnings come from the dev CSP.
- **Direct `curl -X POST /api/login/` returns 403 (CSRF).** Login must run in-page via `browser_evaluate` so cookies and CSRF tokens flow. The in-page recipe above is the only path that works from an agent context. The standard API auth path for non-browser calls is the personal API key from `hogli dev:api-key` as `Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef`.
- **`.env.local` may use 1Password refs.** Without `op` installed, refs become literal strings (e.g. `OPENAI_API_KEY=op://...`) and downstream services fail with cryptic auth errors. Install `op` or replace with literals.

## Troubleshooting

- **`hogli up -d` exits with `Another instance of bin/start is already running`** — previous run still active or crashed without cleanup. `mcp__phrocs__get_process_status` shows what's there; if nothing's running, `rm bin/start.lock` and retry.
- **`docker info` fails with `dial unix /Users/<you>/.orbstack/run/docker.sock: ... no such file`** — OrbStack is stopped. `open -a OrbStack`.
- **`/api/projects/@current` returns 500 instead of 401** — Postgres or ClickHouse unreachable. `docker ps | grep posthog-` and look for unhealthy containers; `hogli services:ready` waits for all of them.
- **`POST /api/login/` returns 400 `invalid_credentials`** — the test user hasn't been created. Run `hogli dev:demo-data`.
- **In-page `fetch('/api/login/')` returns 403** — you're calling it from outside the page context (e.g. `page.request.post` rather than `page.evaluate`). Use `evaluate_script` / `browser_evaluate` so the call originates in-page.
