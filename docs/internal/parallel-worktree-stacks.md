# Parallel worktree stacks

Run the app from several git worktrees at the same time, against the machine's single shared dev infra and single database.
Each worktree serves its own copy of the app at its own URL, so multiple agents (or humans) can develop and browser-test in parallel without deploying or duplicating the stack.

## Architecture

The dev stack has two layers, and they scale differently:

- **Shared infra (one per machine).** The docker services — Postgres, ClickHouse, Redis, Kafka, objectstorage, and the prebuilt capture/feature-flags/plugin images — run once, under the `posthog` compose project, publishing on localhost. `/etc/hosts` maps their compose hostnames (`db`, `kafka`, …) to `127.0.0.1`, so any process from any worktree reaches them with the standard env files.
- **Per-worktree app services.** Each worktree runs only the services it is changing (typically Django and the frontend) on a port block derived from a stable per-worktree index, plus its own copy of the Caddy entrypoint proxy. The worktree's proxy routes the services it overrides to the worktree's ports and every other path (capture, flags, webhooks, …) to the shared stack.

The entrypoint proxy is the same Caddy service the main stack runs at `:8010`; `docker-compose.dev.yml` parameterizes its listen port (`PROXY_PORT`) and every upstream port (`PROXY_WEB_PORT`, `PROXY_CAPTURE_PORT`, …) with defaults that preserve single-stack behavior.

## Usage

The worktree's services run under phrocs — the same process manager as the main stack — so the verbs, the TUI, and the detached workflow are the ones you already know from `hogli start` / `hogli wait` / `hogli stop`.

From inside a worktree, with the shared infra already running (`hogli start -d` in the main checkout, or at least the docker services):

```bash
bin/worktree-stack start               # phrocs TUI: proxy + backend + frontend
bin/worktree-stack start -d            # detached, for agents
bin/worktree-stack start proxy backend # autostart just these
bin/worktree-stack wait                # block until ready (agents pair this with start -d)
bin/worktree-stack url                 # the app URL for this worktree
bin/worktree-stack env                 # export lines for this worktree's ports
bin/worktree-stack stop                # also: down
```

`start` allocates the worktree's index on first use (registry in `<main checkout>/.posthog/worktree-stack-registry`), sources the standard env files the way `bin/start` does, generates a phrocs config under `.worktree-stack/` in the worktree, and hands off to phrocs.

Every service the worktree can override appears in the phrocs sidebar; services not selected on `start` are defined with `autostart: false`, so starting or stopping an individual one is a keypress in the TUI, exactly like the main stack.
phrocs resolves its control socket per directory, so from inside the worktree plain `hogli wait` and `hogli stop` target this worktree's stack.

Point a browser — or an agent's computer use — at `bin/worktree-stack url`.
Cookies are per-origin, so each worktree's port has its own login session; users live in the shared database, so the same dev credentials work everywhere.

## Port scheme

Index 0 is the main checkout (plain single stack, untouched defaults). Worktree `i` gets:

| Service                  | Port        | i=1  |
| ------------------------ | ----------- | ---- |
| App URL (Caddy proxy)    | 8010 + 100i | 8110 |
| Django (granian)         | 8000 + 100i | 8100 |
| Vite dev server          | 8234 + 100i | 8334 |
| debugpy (with `DEBUG=1`) | 5678 + i    | 5679 |
| plugin-server HTTP       | 6739 + 100i | 6839 |

The 100 spacing keeps derived ports clear of the fixed infra ports (5432, 6379, 8123, 9000, 9092, 7233).

## Semantics and caveats

- **One database.** All stacks share Postgres and ClickHouse. Migrations are not run automatically; if `/_health` reports migrations out of date, run `python manage.py migrate` from the most-migrated branch. Worktrees whose branches carry conflicting migrations will fight — coordinate schema changes through the shared DB deliberately.
- **Queue consumers compete.** `celery-worker` and `nodejs` (plugin-server) started per-worktree join the same consumer groups as the shared stack. Each message is processed exactly once, by either a shared or a worktree instance, nondeterministically. To route deterministically to your instance, stop the shared one while testing.
- **`celery-beat` is a singleton.** Never run it per worktree; `worktree-stack` refuses.
- **Overriding more services.** Any Caddy upstream can be pointed at a worktree port via the `PROXY_*` variables when starting the worktree proxy, e.g. a locally built capture on `PROXY_CAPTURE_PORT`. The plumbing accepts any service; only backend/frontend/celery-worker/nodejs have first-class recipes in `worktree-stack`.

## Why not mirrord

mirrord's traffic-shimming model (each client steals the subset of requests matching its filter) was evaluated for this workflow.
It requires the workloads to run in Kubernetes, and concurrent per-user filtered stealing of one service is an operator feature of the paid tiers.
On a single machine the Caddy overlay achieves the same "shim only what you changed" result with the stack's existing localhost architecture.
