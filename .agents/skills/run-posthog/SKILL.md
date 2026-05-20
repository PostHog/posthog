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

Verify and screenshot via the driver:

```bash
node .agents/skills/run-posthog/driver.mjs
```

What the driver does:

| step                              | what it checks                                                             |
| --------------------------------- | -------------------------------------------------------------------------- |
| `GET :8010/_health`               | Envoy-style proxy in front of Django + Vite is alive                       |
| `GET :8010/`                      | redirects to `/preflight` or `/login` (200/302)                            |
| `GET :8010/api/projects/@current` | returns a structured 401 — proves Django + DB are reachable                |
| Playwright nav to `:8010/`        | renders the preflight/login page in headless Chromium                      |
| screenshot                        | written to `/tmp/posthog-shots/<timestamp>.png`, symlinked to `latest.png` |

Flags:

- `--no-browser` — HTTP smoke only, skip Playwright (useful in CI / no chromium).
- `BASE_URL=...` — override the proxy URL (default `http://localhost:8010`).

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

## Troubleshooting

- **`hogli up -d` exits with `Another instance of bin/start is already running (lock file: bin/start.lock)`** — a previous run is still active or crashed without cleanup. Check `phrocs status` (or `lsof bin/start.lock`); if nothing's there, `rm bin/start.lock` and retry.
- **`docker info` fails with `dial unix /Users/<you>/.orbstack/run/docker.sock: connect: no such file or directory`** — OrbStack is stopped. `open -a OrbStack` (macOS) or restart the daemon; sockets reappear under `~/.orbstack/run/`.
- **Driver fails on `Cannot find module 'playwright'`** — Playwright is a frontend dep. Run from the repo root after `pnpm install`, or invoke with `pnpm exec node .agents/skills/run-posthog/driver.mjs`.
- **First navigation in the driver times out (`page.goto` > 60s)** — Vite is compiling routes on demand. Re-run; the second pass uses the warm cache and completes in <5s.
- **`/api/projects/@current` returns 500 instead of 401** — Postgres or ClickHouse isn't reachable. `docker ps | grep posthog-` and look for non-healthy containers; `hogli services:ready` waits for all of them.
