"""Isolate the golden failure: does hogpanion come up on a disk_gib=100 box (no bootstrap)?"""
import time

from hog import client

c = client()
box = c.create(cpus=2, memory_mib=4096, disk_gib=100,
               ssh_public_key=open("/tmp/seed_key.pub").read().strip(),
               kind="ci", ttl_seconds=900, name="diag-disk100")
print("created:", box.id, box.status, "disk_gib=100 no-bootstrap", flush=True)
try:
    for i in range(60):  # up to ~5min
        box.refresh()
        if box.status == "running":
            print(f"running after ~{i*5}s", flush=True)
            break
        if box.status == "failed":
            print(f"FAILED (status) after ~{i*5}s", flush=True)
            raise SystemExit(0)
        time.sleep(5)
    else:
        print(f"still {box.status} after 5min", flush=True)
        raise SystemExit(0)
    r = box.exec(["sh", "-c", "uname -r; df -h / | tail -1"], timeout_seconds=30)
    print(f"EXEC ok exit={r.exit_code}: {r.stdout!r}", flush=True)
    print("=> hogpanion comes up fine WITH disk_gib=100 → 100GiB disk is NOT the cause", flush=True)
finally:
    box.destroy()
    print("destroyed", flush=True)
