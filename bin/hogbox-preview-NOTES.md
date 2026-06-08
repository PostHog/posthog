# Hogbox preview — status & architecture

Per-PR PostHog preview environments on [hogland](https://github.com/PostHog/hogland)
hogboxes (Firecracker microVMs), instead of DigitalOcean droplets (`ci-hobby.yml`).

## Proven (2026-06-08)

End-to-end, by hand against hogland prod-us:

1. `bin/hogbox-ci.py` — CI runner joins the tailnet (`tag:hogland-ci`, WIF OIDC),
   mints a GitHub OIDC token, and drives hogland via the `posthog-hogland` SDK.
   **Green.**
2. `devbox-golden` snapshot built (`scripts/devbox-setup.sh` on hogland) — a
   warmed PostHog dev stack (Docker + repo + pre-pulled images), 16 vCPU/64 GiB.
3. `bin/hogbox-preview.py` — restore the golden → stack **healthy in ~3 min** →
   reachable, and the **full PostHog UI renders** via a local `ssh -L` forward.

## Decision: follow hobby (Docker), not the dev stack

A preview should run the **hobby stack** (`docker-compose.hobby.yml` + the PR's
built image, Caddy serving everything at one URL), **not** the dev stack
(`hogli up`). The dev stack is for interactive devboxes and is preview-hostile:
it serves the frontend from a separate vite/HMR server on `:8234` (only granian
is on `:8010`), it's a dev build, and there's no single serving URL. Hobby
collapses all of that — **one URL** via Caddy, a **prod build**, and the
`SITE_URL: https://$DOMAIN` mechanism PostHog needs. It also lets us **reuse
`bin/hobby-ci.py` and the hobby compose** rather than reinvent stack lifecycle.

`bin/hogbox-preview.py` (dev-stack flow) proved the hogbox *mechanics* — restore,
detached exec, poll, `SITE_URL`, reachability — but the **go-forward is the
hobby stack inside the hogbox**. The golden then simplifies to "Docker + hobby
compose + base images pulled" (no heavy dev-stack warm).

## Serving / the path-prefix wall

PostHog emits **absolute** paths (`/preflight`, `/static/...`), so it only
renders when served at a URL **root**. hogplane's authenticated proxy
(`/v1/hogboxes/<id>/proxy/<port>/...`) is a path prefix — great for **auth**
(tailnet users reach it with no token via Tailscale identity) but it mangles
the SPA. With hobby this is now a **single port** (Caddy `:80`), so root-serving
needs only one mapping: a `tailscale serve` gateway port, or `ssh -L` locally.

## Open items (ordered)

1. **Build the hobby flow in a hogbox** (the go-forward): in the box, run
   `docker-compose.hobby.yml` with the PR's built image and `SITE_URL=<preview
   url>`, Caddy serving on one port. Reuse `bin/hobby-ci.py` where possible.
   Replaces the `hogli up` path in `bin/hogbox-preview.py`.
2. **Root-serving gateway for tailnet users.** A central `tailscale serve`
   "preview gateway" (one HTTPS port per active preview → that box's Caddy)
   gives each preview a clean **root** URL on the tailnet without per-box
   Tailscale (dropped for scale — see #hogland). Then `PREVIEW_URL` = that URL.
3. **Golden simplifies.** With hobby, the snapshot only needs Docker + the hobby
   compose + base images pulled — not the heavy dev-stack warm in
   `scripts/devbox-setup.sh`. Also resolve cluster: the golden lives on prod-us
   but the CI probe targets dev — build it on the CI-target cluster and add a
   `github_oidc` TrustMapping there for `PostHog/posthog`.
4. **SDK/server bug:** restore "omit cpus/memory to inherit" doesn't work —
   `applyDefaults` fills 1/1024/10 and the match-check rejects. Pass matching
   sizing for now; fix upstream in hogland.

## TTL

Previews are long-lived: `PREVIEW_TTL` defaults to **1 week** (hogland's max);
the reaper extends on API activity. (Not 1 h — that was a test backstop.)
