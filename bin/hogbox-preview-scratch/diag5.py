"""Inline-files vs setup-script: bootstrap = heredocs of the 4 overlay files
(the exact suspect content + mechanism) + a quick marker. No 45m setup.
hogpanion fails -> the overlay inline-files break it; works -> devbox-setup.sh is the culprit."""
import pathlib
import time

from hog import client

R = pathlib.Path("/Users/julian/workspace/hogland/images/devbox-overlay")
files = {
    "/tmp/hog-devbox-init": R / "hog-devbox-init",
    "/tmp/hog-devbox-init.service": R / "hog-devbox-init.service",
    "/tmp/hog-devbox-startup": R / "hog-devbox-startup",
    "/tmp/hog-devbox-startup.service": R / "hog-devbox-startup.service",
}
parts = ["#!/bin/sh"]
for i, (dst, src) in enumerate(files.items()):
    d = f"ZZHOGEOF{i}ZZ"
    content = src.read_text()
    assert d not in content, "delimiter collision"
    parts.append(f"cat > {dst} <<'{d}'\n{content}\n{d}")
parts.append("echo hi > /tmp/boot-ran")
boot = "\n".join(parts) + "\n"
print(f"bootstrap size: {len(boot)} bytes (4 overlay files heredoc'd)", flush=True)

c = client()
box = c.create(cpus=2, memory_mib=4096, disk_gib=10,
               ssh_public_key=open("/tmp/seed_key.pub").read().strip(),
               bootstrap=boot, kind="ci", ttl_seconds=900, name="diag-overlay")
print("created:", box.id, box.status, flush=True)
try:
    for i in range(48):  # ~4min
        box.refresh()
        if box.status == "running":
            print(f"running after ~{i*5}s", flush=True)
            break
        if box.status == "failed":
            print(f"FAILED (status) after ~{i*5}s — {getattr(box.view,'fail_reason','')!r}", flush=True)
            raise SystemExit(0)
        time.sleep(5)
    else:
        print(f"still {box.status} after 4min → the OVERLAY INLINE-FILES break hogpanion", flush=True)
        raise SystemExit(0)
    r = box.exec(["sh", "-c", "cat /tmp/boot-ran; ls -la /tmp/hog-devbox-*"], timeout_seconds=30)
    print(f"EXEC ok exit={r.exit_code}: {r.stdout!r}", flush=True)
    print("=> overlay inline-files are FINE → devbox-setup.sh content is the culprit", flush=True)
finally:
    box.destroy()
    print("destroyed", flush=True)
