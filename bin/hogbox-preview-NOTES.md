# Hogbox preview — status, decisions, and how to continue

Per-PR PostHog preview environments on [hogland](https://github.com/PostHog/hogland)
hogboxes (Firecracker microVMs), as an alternative to the ci-hobby DigitalOcean
droplets.

> **→ Productionised in [`tools/hogbox-preview/`](../tools/hogbox-preview/).**
> The inline `bin/hogbox-preview.py` + `bin/hogbox-preview-scratch/` here are the
> exploration that proved the recipe; the class-based, layer-agnostic version
> (swap hogland ↔ DigitalOcean without touching the stack) lives in `tools/`.
>
> **Current (2026-06-17):** the tool is pen-backed (a stable `<pen-id>` URL that
> survives box churn), builds the PR's frontend (path-filtered), posts a GitHub
> Deployment + a staged sticky comment, and tears down on close / label-removal /
> a daily stale-sweep. hogland #319 (pen-id edge routing) is live on prod-us. The
> notes below are the original exploration; see `tools/hogbox-preview/README.md`
> for the current design.
> The **edge/serving blocker is solved** — `box-front` shipped to hogland main, so
> a box created with `--web-port` is reachable at its own
> `https://<box>.boxes.hogland.<env>.posthog.dev/` (no SSH forward). Full SPA
> renders end-to-end (2026-06-10), incl. **demo data via `manage.py n`** (same
> step hobby/sandbox use — we now seed it, previously we didn't).

## TL;DR (2026-06-08)

- **CI runner → hogland connectivity: GREEN** — `bin/hogbox-ci.py` +
  `.github/workflows/ci-hogbox-preview.yml`.
- **`devbox-golden` snapshot built (PROD-US):** `snap-a39dc8a30b87`
  (16 vCPU / 64 GiB). Durable — survives across days (it's a snapshot).
- **Preview proven end-to-end:** restore golden → PostHog stack healthy in
  **~3 min** → the **full UI renders** through SSH forwards.
- **Open:** which in-box stack to standardize on (docker `dev-full` vs the
  `hogli` dev stack). The tailnet **serving/gateway is a separate PR (Julian).**

## Plumbing that's shipped

- **Tailnet join for CI** (`tag:hogland-ci`, WIF/OIDC, no secret): cloud-infra
  **#8546** (ACL grant) + **#8570** (drop ':' from the WIF description). Federated
  identity is live; repo vars `TS_HOGLAND_CI_CLIENT_ID` / `TS_HOGLAND_CI_AUDIENCE`
  need to be set on `PostHog/posthog` (the `gh variable set` was blocked by the
  safety classifier — set them by hand; values are non-secret).
- **hogplane GitHub-OIDC audience:** hogland **#279** (merged) — per-env
  `HOG_GITHUB_OIDC_AUDIENCE` (`hogland.<env>.posthog.dev`).
- **Keyless `access_type=none`:** hogland **#280** (draft, green) — service boxes
  don't need an SSH key.
- A `github_oidc` TrustMapping for `PostHog/posthog` exists on **dev** (created
  in the console). The probe authenticated as `svc-ci-preview-…`.

## The golden snapshot

- Recipe: `scripts/devbox-setup.sh` in hogland (Docker + posthog clone + warmed
  dev stack). Built with `hogland snapshot-build --alias devbox-golden`.
- **Gotcha:** the homebrew `hogland` CLI is too stale (fails `BoxView` decode on
  the new `expires_at` field). Build a current one: in the hogland repo,
  `go build -o /tmp/hogland ./cmd/hogland`.
- **Gotcha:** snapshot-build SSH-polls the seed box for a success marker; it uses
  your _default_ ssh key. We installed `/tmp/seed_key` as `~/.ssh/id_ed25519`.
- The golden is on **prod-us**; the CI probe targets **dev**. Reconcile: build the
  golden on dev too (+ a TrustMapping there), or repoint the preview to prod-us.

## Stack decision (OPEN — pick one tomorrow)

Constraint (Julian): **don't invent a new serving path — use `hogli` daemonized
OR docker.** Options, with the trade-off:

| Path                                         | Speed                                 | Source                                        | Serving                                                                       |
| -------------------------------------------- | ------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------- |
| hobby (`docker-compose.hobby.yml`)           | slow (full image build, ~tens of min) | built image                                   | one URL, Caddy, prod                                                          |
| `docker-compose.sandbox.yml` (`bin/sandbox`) | fast (image built once + caches)      | **git CLONE into a volume** (Julian dislikes) | Caddy `:8000` + vite `JS_URL`                                                 |
| **`docker-compose.dev-full.yml`**            | fast (image once + live code)         | **in-place `.:/app/posthog`** ✅              | **single `:8000`**, `./bin/docker-server-unit`, frontend from `frontend/dist` |
| `hogli` dev stack (what the golden runs)     | fastest                               | in-place, run from source                     | backend `:8010` + **vite `:8234`** (two ports)                                |

**Leading candidate: `docker-compose.dev-full.yml`** — full docker, **in-place
source**, single port `:8000`. Caveats: last touched 2026-04-28 (lightly stale
but `extends docker-compose.base.yml`, which is current), and the `.:/app/posthog`
mount **shadows the image's built frontend**, so you must `pnpm build` in-place to
populate `frontend/dist` (the only real cost — incremental on FE diffs, never a
full image rebuild). Settings: frontend served from `frontend/dist`
(`posthog/settings/web.py:206,348`); `SITE_URL`/`JS_URL` are the serving knobs
(hobby sets `SITE_URL: https://$DOMAIN`; `ALLOWED_HOSTS` defaults to `*`).

## What I trialed today (WORKS now, but EPHEMERAL)

- Box **`box-9cfdc5386a75`** (prod-us, restored golden, `hogli` dev stack running).
  **TTL was ~1 h → it's reaped by tomorrow.** The golden snapshot persists.
- Two SSH forwards (**session-bound — they die when this CLI session ends**):
  - `localhost:18010` → box `:8010` (backend; `:8010` was taken by OrbStack so we
    used `:18010`)
  - `localhost:8234` → box `:8234` (vite frontend; `JS_URL` already points here)
- `http://localhost:18010/` renders the **full PostHog UI** (frontend loads via
  the `:8234` forward). The dev stack serves the SPA from vite live, not
  `frontend/dist`.
- **Caveat:** the box's `SITE_URL` is still `localhost:8010` ≠ `:18010`, so
  login/CSRF may reject. To fully match: set `SITE_URL=http://localhost:18010`
  (+ `JS_URL`) in the box and bounce the backend (`./bin/start-backend`).

## Continue tomorrow

1. **Get back to a live preview** (box + forwards are gone):
   - Confirm golden: `/tmp/hogland --host https://hogland.hedgehog-kitefin.ts.net snap resolve devbox-golden`
     (rebuild the CLI first: `go build -o /tmp/hogland ./cmd/hogland` in hogland).
   - Restore + bring up: `bin/hogbox-preview-scratch/` has the working scripts.
     `HOGENV=prod-us SNAP=snap-a39dc8a30b87 KEEP=1 python preview.py` restores
     (pass matching sizing 16/64/100 — see bug below), reuses with `BOX_ID=`.
   - SSH in: `hog@<public_ip>:<guest_ssh_port>` (from `hogland box get <id>`),
     key `/tmp/seed_key` (`ssh -i /tmp/seed_key -o IdentitiesOnly=yes`). Forward
     `18010:localhost:8010` and `8234:localhost:8234`.
2. **Decide the stack:** prototype `docker compose -f docker-compose.dev-full.yml up`
   in a box against the in-place checkout (build FE once), confirm `:8000` serves
   the whole UI, and fix dev-full's staleness — vs. keeping the dev-stack
   two-forward path.
3. **Golden ↔ cluster:** build the golden on dev (+ TrustMapping) or repoint CI.
4. The **serving/gateway** (tailnet root URL): Julian's separate PR.

### Known gotchas (all hit today)

- **SDK restore "omit cpus/memory to inherit" is BROKEN** — `applyDefaults` fills
  1/1024/10 and the match-check rejects. Pass sizing that matches the snapshot
  exactly (16/64/100). Fix upstream in hogland.
- **SDK default timeout too short** for restores + long execs — set
  `Hogland(timeout=httpx.Timeout(read=2000))`.
- **hogd caps single-exec duration** — `hogli up` must run detached + polled, not
  one blocking exec.
- **`redis-cluster` crash-loops on restore** (snapshot-safety, like the
  kafka/redpanda wipe in `scripts/devbox-setup.sh`).

## Scripts: `bin/hogbox-preview-scratch/`

Local-iteration scratch (read creds from `~/.config/hogland/config.json`; set
`HOGENV=dev|prod-us`). Kept for reference / to pick up tomorrow:

- `hog.py` — Hogland client factory (env switch + long timeout).
- `preview.py` — restore/reuse golden → detached `hogli up` → poll web port →
  proxy probe. The proven orchestration.
- `assess.py` — in-box inspection via exec (ports, docker ps, env, logs).
- `diag*.py` — the hogpanion/networking/OOM diagnosis (how we found the dev-node
  flakiness + the 172.16/172.20 vs Docker non-issue).
- `restore.py`, `cleanup.py`, `watch_*.sh` — restore/cleanup/placement-watch utils.
