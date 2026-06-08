"""Restore devbox-golden as a long-lived box for local preview iteration.

kind=preview (not devbox) so the per-user devbox-init/startup units self-skip;
the warmed env (docker + /home/hog/posthog + cached images) is on disk
regardless. Leaves the box RUNNING (no context manager) so we can fire exec
calls at it across iterations. ttl is a 1h backstop reaper.
"""
from hog import client

c = client()
print("me:", c.me().email, flush=True)

box = c.create(
    snapshot_id="alias:devbox-golden",
    kind="preview",
    ttl_seconds=3600,
    name="preview-iter",
)
print("BOX_ID:", box.id, flush=True)
print("status:", box.status, flush=True)
spec = box.spec
print("spec:", getattr(spec, "cpus", "?"), "cpu /", getattr(spec, "memory_mib", "?"), "MiB", flush=True)
