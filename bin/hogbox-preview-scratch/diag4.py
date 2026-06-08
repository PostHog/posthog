"""Size vs content: a ~24KB bootstrap that's pure comments (runs instantly).
If hogpanion comes up -> size is fine, the golden's failure is CONTENT.
If hogpanion hangs    -> a large MMDS bootstrap breaks hogpanion startup (SIZE)."""
import time

from hog import client

pad = "#!/bin/sh\n" + ("# padding line to fill the MMDS document\n" * 580) + "echo hi > /tmp/boot-ran\n"
print(f"bootstrap size: {len(pad)} bytes", flush=True)

c = client()
box = c.create(cpus=2, memory_mib=4096, disk_gib=10,
               ssh_public_key=open("/tmp/seed_key.pub").read().strip(),
               bootstrap=pad, kind="ci", ttl_seconds=900, name="diag-bigboot")
print("created:", box.id, box.status, flush=True)
try:
    for i in range(60):  # up to ~5min
        box.refresh()
        if box.status == "running":
            print(f"running after ~{i*5}s", flush=True)
            break
        if box.status == "failed":
            print(f"FAILED (status) after ~{i*5}s — {getattr(box.view,'fail_reason','')!r}", flush=True)
            raise SystemExit(0)
        time.sleep(5)
    else:
        print(f"still {box.status} after 5min → big MMDS bootstrap breaks hogpanion (SIZE is the cause)", flush=True)
        raise SystemExit(0)
    r = box.exec(["cat", "/tmp/boot-ran"], timeout_seconds=30)
    print(f"EXEC ok exit={r.exit_code}: {r.stdout!r}", flush=True)
    print("=> ~24KB bootstrap WORKS → size is fine; the golden's failure is CONTENT", flush=True)
finally:
    box.destroy()
    print("destroyed", flush=True)
