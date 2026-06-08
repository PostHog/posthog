"""Prove the root cause: simulate Docker grabbing 172.20.0.0/16 inside a box
and watch hogpanion (reached by hogd via the veth 172.20.x route) drop."""
import time

from hog import client

c = client()
box = c.create(cpus=1, memory_mib=1024, disk_gib=10,
               ssh_public_key=open("/tmp/seed_key.pub").read().strip(),
               kind="ci", ttl_seconds=600, name="diag-route")
for _ in range(40):
    box.refresh()
    if box.status == "running":
        break
    time.sleep(3)
print("box", box.id, box.status, flush=True)

r = box.exec(["sh", "-c", "ip -4 addr show | grep -E 'inet |eth'; echo ROUTES; ip -4 route"], timeout_seconds=20)
print("BASELINE NETWORKING:\n" + r.stdout, flush=True)

# Defer the collision 3s so this exec's own reply makes it back first.
# blackhole route = definitive (no carrier dependency): drops everything to 172.20/16.
box.exec(["sh", "-c",
          "nohup sh -c 'sleep 3; ip route add blackhole 172.20.0.0/16' "
          ">/tmp/bh.log 2>&1 & echo 'blackhole 172.20.0.0/16 scheduled in 3s'"],
         timeout_seconds=20)
print("scheduled blackhole 172.20.0.0/16; waiting...", flush=True)
time.sleep(7)

try:
    r3 = box.exec(["echo", "still-alive"], timeout_seconds=15)
    print(f"POST-collision exec exit={r3.exit_code} out={r3.stdout!r} -> hogpanion SURVIVED", flush=True)
except Exception as e:  # noqa: BLE001
    print(f"POST-collision exec FAILED: {type(e).__name__}: {str(e)[:160]}", flush=True)
    print("=> CONFIRMED: a 172.20.0.0/16 route inside the guest blackholes hogpanion's reply path", flush=True)
finally:
    try:
        box.destroy()
        print("destroyed", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"destroy err (ttl 600s will reap): {e}", flush=True)
