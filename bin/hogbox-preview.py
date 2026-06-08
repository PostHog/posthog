#!/usr/bin/env python3
"""Spin up a PostHog preview environment on a hogland hogbox.

Restores the `devbox-golden` snapshot (a warmed PostHog dev stack), checks out
the target branch, points the stack at the URL it'll be served under, brings it
up, and reports the URL. Built to run in CI (one preview per PR) but also runs
locally against hogland-dev / prod-us.

NOTE: this is the dev-stack (`hogli up`) flow — it PROVED the hogbox mechanics
(restore, detached exec, poll, SITE_URL, reachability) but the go-forward is the
HOBBY stack (docker-compose.hobby.yml + the PR image, Caddy on one URL) inside
the box. See bin/hogbox-preview-NOTES.md for the decision and the open items.

This is the productionised form of the manual flow proven end-to-end on
2026-06-08 (restore golden -> stack healthy in ~3min -> reachable + renders the
full UI). The non-obvious lessons are baked in below so nobody re-pays them:

  - RESTORE SIZING. The "omit cpus/memory to inherit" path is documented but
    broken — applyDefaults fills 1/1024/10 and the restore-match check then
    rejects. So pass sizing that MATCHES the snapshot exactly (the golden is
    16 vCPU / 64 GiB / 100 GiB). [hogland SDK/server bug to fix upstream.]

  - SDK TIMEOUT. A snapshot restore (mount the 100 GiB chunkfs + memory restore)
    and a long exec both exceed the SDK's default httpx read timeout. Give the
    client generous headroom (read ~2000s).

  - hogd CAPS SINGLE-EXEC DURATION. You cannot block one exec on `hogli up`
    (it trips hogd's hog-exec deadline). Launch the stack DETACHED (setsid +
    redirect + `&`) and POLL for the web port with short execs.

  - SERVING URL (like hobby). PostHog must know the URL it's served under or it
    emits wrong absolute links. hobby sets `SITE_URL: https://$DOMAIN`; do the
    same here (SITE_URL + JS_URL + OBJECT_STORAGE_PUBLIC_ENDPOINT) before
    `hogli up`. ALLOWED_HOSTS defaults to `*`, so the host itself is accepted.

  - ROOT-SERVING vs PATH PREFIX. hogplane's authenticated proxy
    (`/v1/hogboxes/<id>/proxy/<port>/...`) reaches the box and authenticates
    tailnet users with no token — but it's a PATH PREFIX, and PostHog emits
    absolute paths (`/preflight`, `/static/...`) that then resolve at the origin
    and 404. The app renders correctly only when served at a URL ROOT. Local:
    `ssh -L`. Tailnet-for-others: a central `tailscale serve` gateway giving
    each preview a root URL (TODO — see PREVIEW_NOTES).

  - FRONTEND DEV SERVER. The dev stack serves the SPA assets from a separate
    vite server on :8234; only the Django/granian backend is on :8010. A
    fully-interactive preview needs both ports exposed or a prod frontend build
    (TODO).

  - redis-cluster crash-loops on restore (snapshot-safety, same class as the
    kafka/redpanda wipe in scripts/devbox-setup.sh) — doesn't block login.

Env:
  HOG_HOST   hogland base URL (tailnet), e.g. https://hogland.hedgehog-kitefin.ts.net
  HOG_TOKEN  credential (GitHub OIDC JWT in CI; an APIToken locally)
  PREVIEW_SNAPSHOT   snapshot id or "alias:devbox-golden" (default)
  PREVIEW_BRANCH     posthog branch to check out (default: leave golden's)
  PREVIEW_URL        the URL the preview is served under -> SITE_URL (required
                     for correct links; defaults to the proxy URL once the box
                     exists, which renders the login page but not deep links)
  PREVIEW_TTL        box TTL seconds (default 604800 = 1 week, the max)
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request

import httpx
from hogland import Hogland

WEB_PORT = 8010
# Golden is 16/64/100; must match on restore (see module docstring).
CPUS, MEM_MIB, DISK_GIB = 16, 65536, 100
SNAP = os.environ.get("PREVIEW_SNAPSHOT", "alias:devbox-golden")
BRANCH = os.environ.get("PREVIEW_BRANCH", "")
TTL = int(os.environ.get("PREVIEW_TTL", str(7 * 24 * 3600)))  # 1 week (reaper extends on activity)

# Runs a hogli subcommand as the hog user inside the warmed Flox env. Written to
# the box as a file so the nested quoting lives in one place.
RUNHOGLI = r'''#!/bin/bash
exec sudo -u hog -H env GIT_CONFIG_GLOBAL=/dev/null bash -c 'cd /home/hog/posthog && flox activate -- bash -c '"'"'source $UV_PROJECT_ENVIRONMENT/bin/activate && exec "$@"'"'"' _ "$@"' _ "$@"
'''


def client() -> Hogland:
    # Restores + long execs far exceed the SDK default read timeout.
    return Hogland(timeout=httpx.Timeout(connect=15.0, read=2000.0, write=120.0, pool=120.0))


def sh(box, cmd, *, timeout=30, label=None):
    if label:
        print(f"[preview] $ {label}", flush=True)
    return box.exec(["sh", "-c", cmd], timeout_seconds=timeout)


def main() -> int:
    c = client()
    print("[preview] authenticated as:", c.me().email, flush=True)

    box_id = os.environ.get("BOX_ID")
    if box_id:
        box = c.get(box_id)
        print(f"[preview] reusing {box.id} ({box.status})", flush=True)
    else:
        box = c.create(snapshot_id=SNAP, cpus=CPUS, memory_mib=MEM_MIB, disk_gib=DISK_GIB,
                       kind="preview", ttl_seconds=TTL, name="preview")
        print(f"[preview] restored {box.id} from {SNAP}", flush=True)

    # Default the serving URL to the authenticated proxy (renders login; deep
    # links need a root URL via a gateway — see notes).
    preview_url = os.environ.get("PREVIEW_URL") or box.proxy_url(WEB_PORT).rstrip("/")

    try:
        box.write_file("/tmp/runhogli.sh", RUNHOGLI.encode(), mode="0755", mkdir=True)

        if BRANCH:
            sh(box, f"sudo -u hog -H git -C /home/hog/posthog fetch --depth 1 origin {BRANCH} "
                    "&& sudo -u hog -H git -C /home/hog/posthog checkout --force FETCH_HEAD",
               timeout=300, label=f"checkout {BRANCH}")

        # Point PostHog at the URL it's served under (hobby parity). Written to
        # the dev-stack env so granian/django pick it up on start.
        sh(box, "cat >> /home/hog/posthog/.env <<EOF\n"
                f"SITE_URL={preview_url}\n"
                f"JS_URL={preview_url}\n"
                f"OBJECT_STORAGE_PUBLIC_ENDPOINT={preview_url}\n"
                "EOF", label="set SITE_URL")

        # Bring the stack up DETACHED (hogd caps single-exec duration), then poll.
        up = sh(box, f"ss -ltn 2>/dev/null | grep -q ':{WEB_PORT} ' && echo UP || echo DOWN")
        if "UP" not in up.stdout:
            sh(box, "setsid /tmp/runhogli.sh hogli up -d >/tmp/hogli-up.log 2>&1 </dev/null & echo launched",
               timeout=60, label="hogli up -d (detached)")

        for i in range(80):  # ~20 min
            chk = sh(box, f"ss -ltn 2>/dev/null | grep -q ':{WEB_PORT} ' && echo WEBUP || "
                          "(echo WEBDOWN; tail -2 /tmp/hogli-up.log 2>/dev/null)")
            print(f"[preview] poll {i} (~{i*15}s): {chk.stdout.strip()[:200]}", flush=True)
            if "WEBUP" in chk.stdout:
                break
            time.sleep(15)
        else:
            print("[preview] web port never came up within ~20min", flush=True)
            return 1

        # Probe through the proxy (confirms reach + auth).
        proxy = box.proxy_url(WEB_PORT)
        for attempt in range(1, 11):
            try:
                req = urllib.request.Request(proxy, headers={"Authorization": f"Bearer {c.token}"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    print(f"[preview] proxy probe -> {r.status}", flush=True)
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[preview] probe {attempt}: {e}", flush=True)
                time.sleep(8)

        print(f"\n[preview] BOX={box.id}", flush=True)
        print(f"[preview] PROXY_URL={proxy}", flush=True)
        print(f"[preview] SITE_URL={preview_url}", flush=True)
        print("[preview] DONE. Tailnet users open PROXY_URL (login renders; deep links need a "
              "root-serving gateway — see PREVIEW_NOTES). For a full local view: "
              f"ssh -L 18010:localhost:{WEB_PORT} hog@<box-ip> -p <ssh-port>, then http://localhost:18010/",
              flush=True)
        return 0
    finally:
        if os.environ.get("PREVIEW_DESTROY"):
            box.destroy()
            print(f"[preview] destroyed {box.id}", flush=True)
        else:
            print(f"[preview] left {box.id} running (TTL {TTL}s)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
