"""Does hogpanion come up on a box with a TRIVIAL bootstrap? Isolates
'any bootstrap breaks hogpanion' vs 'the large devbox bootstrap specifically'."""
import time

from hog import client

c = client()
box = c.create(cpus=2, memory_mib=4096, disk_gib=10,
               ssh_public_key=open("/tmp/seed_key.pub").read().strip(),
               bootstrap="#!/bin/sh\necho hi > /tmp/boot-ran\n",
               kind="ci", ttl_seconds=900, name="diag-bootstrap")
print("created:", box.id, box.status, "trivial bootstrap", flush=True)
try:
    for i in range(48):  # up to ~4min
        box.refresh()
        if box.status == "running":
            print(f"running after ~{i*5}s", flush=True)
            break
        if box.status == "failed":
            print(f"FAILED (status) after ~{i*5}s — {getattr(box.view,'fail_reason','')!r}", flush=True)
            raise SystemExit(0)
        time.sleep(5)
    else:
        print(f"still {box.status} after 4min → hogpanion likely not coming up (same as golden)", flush=True)
        raise SystemExit(0)
    r = box.exec(["cat", "/tmp/boot-ran"], timeout_seconds=30)
    print(f"EXEC ok exit={r.exit_code}: {r.stdout!r}", flush=True)
    print("=> trivial bootstrap WORKS → the golden's LARGE bootstrap is the culprit", flush=True)
finally:
    box.destroy()
    print("destroyed", flush=True)
