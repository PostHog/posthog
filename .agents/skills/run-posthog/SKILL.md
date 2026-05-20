---
name: run-posthog
description: Start, drive, and screenshot the PostHog dev stack. Use when asked to run PostHog, bring the dev environment up, take a screenshot of the app, smoke-test the running app, or verify a UI change against the live app.
---

PostHog is a Django + Vite + Celery + plugin-server monorepo backed by Postgres, ClickHouse, Kafka, Redis, and Temporal in Docker. An agent drives it by booting the stack in detached mode via `hogli`, then running `.claude/skills/run-posthog/driver.mjs` — a Playwright smoke that hits the health endpoints and screenshots the rendered UI.

All paths below are relative to the repo root.

## Prerequisites

The repo bootstraps its own toolchain via [flox](https://flox.dev). You only need three things on the host:

- **flox** 1.12+ — `curl -L https://downloads.flox.dev/by-env/stable/install.sh | sudo bash`
- **Docker** — OrbStack is strongly preferred over Docker Desktop on macOS (`brew install --cask orbstack`)
- **1Password CLI** (optional) — `brew install 1password-cli` if your `.env.local` contains `op://` refs

Everything else (Python, Node, pnpm, hogli, ClickHouse client, etc.) is provisioned by flox and exposed under `.flox/cache/venv/bin/`.

## Setup

First-time only — interactive wizard picks which products' background workers to run:

```bash
hogli dev:setup
```

If you skip it, defaults to `product_analytics` (18 processes — Django, Celery worker/beat, plugin-server, frontend, plus services). Re-run any time to change.

If you see `🔐 Resolving secrets from .env.local via 1Password` and don't have `op`, install it or replace the `op://` references with literals — the dev stack will boot without them, but some features (LLM observability, integration tests) will fail with "missing key" errors.

## Run (agent path)

Bring the stack up in the background, wait for it, and sanity-check the host:

```bash
hogli up -d -y           # forks bin/start under phrocs; downloads GeoLite2 on first run
hogli services:ready -y  # gates on Docker service health (Postgres, CH, Kafka, Redis)
hogli wait -y            # blocks until all phrocs-managed units are ready
hogli doctor             # optional: stale migrations, zombie phrocs, disk pressure
```

Verify and screenshot via the driver (run from the repo root):

```bash
node .claude/skills/run-posthog/driver.mjs
```

What the driver does:

| step                              | what it checks                                                                       |
| --------------------------------- | ------------------------------------------------------------------------------------ |
| `GET :8010/_health`               | Envoy-style proxy in front of Django + Vite is alive                                 |
| `GET :8010/`                      | redirects to `/preflight` or `/login` (200/302)                                      |
| `GET :8010/api/projects/@current` | returns a structured 401 — proves Django + DB are reachable                          |
| Playwright nav to `:8010/`        | renders the preflight/login page in headless Chromium                                |
| screenshot                        | written to `/tmp/posthog-shots/<timestamp>.png`, symlinked to `latest.png`           |
| (with `--login`) signup or reuse  | persists creds + storageState to `/tmp/posthog-shots/{auth.json,storage-state.json}` |
| (with `--login --path=`)          | navigates the authenticated session to `/project/{team_id}{path}`                    |

Flags:

- `--no-browser` — HTTP smoke only, skip Playwright (useful in CI / no chromium).
- `--login` — bootstrap a workspace and screenshot the authenticated home (`/project/{team_id}/home`).
- `--path=/insights` — used with `--login`, screenshot a specific scene. Bare paths (`/insights`, `/dashboard`) are prefixed with `/project/{team_id}`; absolute `/project/...` paths are used verbatim.
- `BASE_URL=...` — override the proxy URL (default `http://localhost:8010`).
- `POSTHOG_DEV_EMAIL=...`, `POSTHOG_DEV_PASSWORD=...` — override the bootstrap credentials. Default email is `test@posthog.com` (the codebase convention); default password is a 3-word phrase that passes Django's password validator on `/api/signup/`.

How `--login` works (mirrors `playwright/utils/playwright-setup.ts:282-291`):

1. Tries cached creds at `/tmp/posthog-shots/auth.json` first. If the cached `storage-state.json` still authenticates against `/api/users/@me/`, the driver skips straight to navigation.
2. Otherwise POSTs to `/api/signup/`. If the user already exists (`code: "unique"`), assumes the configured password matches and continues.
3. Performs the actual login via `page.evaluate(fetch('/api/login/', ...))` — in-page so cookies + CSRF flow automatically. Direct `curl -X POST /api/login/` doesn't work (CSRF middleware rejects it).
4. Persists the session as Playwright `storageState` for the next run.

Why not `/api/setup_test/organization_with_team/` (what the e2e suite uses)? It's gated on `DEBUG=True` (fine in dev), but its implementation calls into ClickHouse-backed code paths that fail on dev stacks where the ClickHouse schema hasn't been fully migrated. Signup is the lower-friction path that exercises the real auth flow.

Stop the stack when done:

```bash
hogli down -y
```

This runs `phrocs stop` — it does NOT take down the Docker services (Postgres, ClickHouse, Kafka, Redis). They keep running so the next `hogli up -d` is fast. To tear those down too: `docker compose -f docker-compose.dev.yml down`.

## Run (human path)

```bash
hogli start         # interactive mprocs TUI — Ctrl-A then a service letter to focus a log
                    # quit with Ctrl-A q. Useless headless.
```

## Test

```bash
hogli test path/to/test.py             # auto-detects Python/Jest/Playwright/Rust/Go
hogli test path/to/test.py --watch     # watch mode
hogli test --changed                   # only files changed vs main
```

## Direct invocation (no full stack)

For PRs touching a single Django function or kea selector, the full stack is overkill. Run only what you need:

```bash
hogli dev:shell-plus       # Django shell with models auto-imported
hogli test path/to/test_module.py::TestClass::test_method
```

`hogli dev:shell-plus` still needs Postgres + ClickHouse up (the `services:ready` check) but not Celery/frontend/plugin-server.

## Gotchas

- **`hogli wait` exits 0 even when phrocs is unreachable.** I saw `phrocs: detached phrocs not reachable: read unix ->/tmp/phrocs-d2553ab9.sock: i/o timeout` on a slow startup, but the wait command still returned 0. Treat `hogli wait` as best-effort — let the driver be the ground truth. If the driver fails, re-run it after a few seconds; first boot can take 60-90s while Django imports modules and Vite warms its cache.
- **Vite serves on `:8234`, NOT the URL you browse.** You browse `http://localhost:8010` (the proxy). The proxy reverse-proxies Vite for `/static/*` and Django for everything else. Hitting `:8234` directly returns 404 on `/` because Vite has no index route at the dev server root.
- **Worktrees share Docker containers but compete for ports.** All worktrees on the same machine resolve to the same `posthog-clickhouse-1` / `posthog-db-1` containers (compose project name is the same), so DB state is global. But port 8000/8010/8234 can only be held by one worktree at a time — kill the granian/vite/phrocs of the other worktree before `hogli up -d` here.
- **CSP warnings and 401s in the browser console are normal pre-auth.** The preflight page tries to fetch `/api/projects/@current`, `/api/users/@me`, and the PostHog.js remote config — all 401 until you sign up. WASM/CSP "Report Only" warnings come from the dev CSP. Don't treat them as failures.
- **`.env.local` is gitignored and may use 1Password refs.** Without `op` installed, those refs become literal strings (e.g. `OPENAI_API_KEY=op://...`) and downstream services fail with cryptic auth errors. Install `op` or replace with literals.
- **`12345678` is the codebase's canonical test password but `--login` can't use it.** `posthog/management/commands/{setup_dev,generate_demo_data,setup_local_api_key}.py` and the Playwright suite (`playwright/utils/playwright-test-core.ts:7-8`) all assume `test@posthog.com` / `12345678`. The signup API rejects it because Django's password validator runs there but is bypassed in management commands. `--login` uses a stronger phrase by default — see `POSTHOG_DEV_PASSWORD` above.
- **HogQL "Unknown table expression identifier 'events'" errors on insight/dashboard scenes.** Symptom of incomplete ClickHouse migrations, not a driver bug. The driver still screenshots fine; the page just renders empty data panels. Fix with `hogli migrations:run` (and untangle any async-migration failures it reports). The fully-canonical bootstrap is `hogli dev:reset`, but it wipes Docker volumes — only run when you don't mind losing local data.

## Troubleshooting

- **`hogli up -d` exits with `Another instance of bin/start is already running (lock file: bin/start.lock)`** — a previous run is still active or crashed without cleanup. Check `phrocs status` (or `lsof bin/start.lock`); if nothing's there, `rm bin/start.lock` and retry.
- **`docker info` fails with `dial unix /Users/<you>/.orbstack/run/docker.sock: connect: no such file or directory`** — OrbStack is stopped. `open -a OrbStack` (macOS) or restart the daemon; sockets reappear under `~/.orbstack/run/`.
- **Driver fails on `Cannot find module 'playwright'`** — Playwright is a frontend dep. Run from the repo root after `pnpm install`, or invoke with `pnpm exec node .claude/skills/run-posthog/driver.mjs`.
- **First navigation in the driver times out (`page.goto` > 60s)** — Vite is compiling routes on demand. Re-run; the second pass uses the warm cache and completes in <5s.
- **`/api/projects/@current` returns 500 instead of 401** — Postgres or ClickHouse isn't reachable. `docker ps | grep posthog-` and look for non-healthy containers; `hogli services:ready` waits for all of them.
- **`--login` fails with `/api/login/ in-page POST returned 403` after a fresh checkout against an existing stack** — there's already a user in the DB with a different password. Either `rm /tmp/posthog-shots/{auth,storage-state}.json` AND export `POSTHOG_DEV_PASSWORD=<the existing one>`, or wipe the user via the Django admin / a separate `psql -c "DELETE FROM posthog_user WHERE email='test@posthog.com'"`.
- **`--login` fails with `signup succeeded but couldn't resolve team_id`** — signup returned 201 but `/api/users/@me/` rejected the session cookie. Almost always means the proxy stripped Set-Cookie (running through an external proxy?) or the session backend is misconfigured. Run `--no-browser` first; if that's clean, restart `hogli up -d` to reset session state.
