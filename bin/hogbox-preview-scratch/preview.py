"""Preview orchestration v2 — restore/reuse the golden, bring the PostHog stack
up DETACHED (hogd caps single-exec duration, so we can't block on hogli up),
poll for the web port, then expose it via the authenticated proxy.

  HOGENV=prod-us SNAP=snap-xxx KEEP=1 python preview.py   # fresh restore
  HOGENV=prod-us BOX_ID=box-xxx KEEP=1 python preview.py  # reuse a box
"""
import os
import sys
import time
import urllib.request

from hog import client

WEB_PORT = int(os.environ.get("WEB_PORT", "8010"))
SNAP = os.environ.get("SNAP", "alias:devbox-golden")

# Runs a hogli subcommand as the hog user inside the warmed Flox env. Written to
# the box as a file so the gnarly nested quoting lives in one place.
RUNHOGLI = r'''#!/bin/bash
exec sudo -u hog -H env GIT_CONFIG_GLOBAL=/dev/null bash -c 'cd /home/hog/posthog && flox activate -- bash -c '"'"'source $UV_PROJECT_ENVIRONMENT/bin/activate && exec "$@"'"'"' _ "$@"' _ "$@"
'''


def sh(box, cmd, *, timeout=30, label=None):
    if label:
        print(f"[preview] $ {label}", flush=True)
    r = box.exec(["sh", "-c", cmd], timeout_seconds=timeout)
    return r


def main() -> int:
    c = client()
    print("[preview] me:", c.me().email, flush=True)

    box_id = os.environ.get("BOX_ID")
    if box_id:
        box = c.get(box_id)
        print(f"[preview] reusing {box.id} ({box.status})", flush=True)
    else:
        box = c.create(snapshot_id=SNAP, cpus=16, memory_mib=65536, disk_gib=100,
                       kind="preview", ttl_seconds=3600, name="preview")
        print(f"[preview] restored {box.id} ({box.status})", flush=True)

    try:
        box.write_file("/tmp/runhogli.sh", RUNHOGLI.encode(), mode="0755", mkdir=True)
        print("[preview] wrote /tmp/runhogli.sh", flush=True)

        # Already up from a prior run? (the previous exec may have launched it)
        up = sh(box, f"ss -ltn 2>/dev/null | grep -q ':{WEB_PORT} ' && echo UP || echo DOWN", timeout=20)
        if "UP" not in up.stdout:
            sh(box,
               "setsid /tmp/runhogli.sh hogli up -d >/tmp/hogli-up.log 2>&1 </dev/null & echo launched",
               timeout=60, label="launch hogli up -d (detached)")

        # Poll for the web port, surfacing log progress.
        ready = False
        for i in range(80):  # ~20 min at 15s
            chk = sh(box,
                     f"echo PORTS; ss -ltn 2>/dev/null | awk 'NR>1{{print $4}}' | grep -oE ':[0-9]+$' | sort -u | tr '\\n' ' '; "
                     f"echo; ss -ltn 2>/dev/null | grep -q ':{WEB_PORT} ' && echo WEBUP || echo WEBDOWN; "
                     "echo LOG; tail -2 /tmp/hogli-up.log 2>/dev/null",
                     timeout=30)
            print(f"[preview] poll {i} (~{i*15}s):\n{chk.stdout.strip()}", flush=True)
            if "WEBUP" in chk.stdout:
                ready = True
                break
            time.sleep(15)

        if not ready:
            print("[preview] web port never came up within ~20min — leaving box for inspection", flush=True)
            return 1

        # Expose via the authenticated proxy and probe it.
        url = box.proxy_url(WEB_PORT)
        print(f"\n[preview] PROXY URL: {url}", flush=True)
        token = c.token
        for attempt in range(1, 13):
            try:
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    body = r.read(4000)
                    print(f"[preview] GET -> {r.status}; first bytes:\n{body[:1500]!r}", flush=True)
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[preview] probe {attempt}: {e}", flush=True)
                time.sleep(8)
        print("\n[preview] DONE — open the PROXY URL above on the tailnet.", flush=True)
        return 0
    finally:
        if not os.environ.get("KEEP"):
            box.destroy()
            print(f"[preview] destroyed {box.id}", flush=True)
        else:
            print(f"[preview] left {box.id} running (KEEP set)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
