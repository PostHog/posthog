"""Quick dev-health probe: does hogpanion come up on a small no-bootstrap box?"""
import time

from hog import client

c = client()
print("me:", c.me().email, flush=True)
box = c.create(cpus=1, memory_mib=1024, disk_gib=10, ssh_public_key=open("/tmp/seed_key.pub").read().strip(),
               kind="ci", ttl_seconds=600, name="diag")
print("created:", box.id, box.status, flush=True)
try:
    # poll to running, then exec (exec == hogpanion reachable)
    for i in range(40):
        box.refresh()
        if box.status == "running":
            print(f"running after ~{i*5}s", flush=True)
            break
        if box.status == "failed":
            print(f"FAILED after ~{i*5}s", flush=True)
            raise SystemExit(0)
        time.sleep(5)
    r = box.exec(["uname", "-a"], timeout_seconds=30)
    print(f"EXEC ok exit={r.exit_code}: {r.stdout!r}", flush=True)
    print("=> hogpanion HEALTHY on dev", flush=True)
finally:
    box.destroy()
    print("destroyed", flush=True)
