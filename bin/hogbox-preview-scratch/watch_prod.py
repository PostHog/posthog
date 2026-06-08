"""Early signal for the prod-us golden build: once the seed places, probe
hogpanion via exec. Exits with a verdict (or times out → fall back to build)."""
import time

from hog import client  # HOGENV=prod-us set in the env

c = client()
seed = None
for _ in range(30):  # find the seed (~10min)
    boxes = list(getattr(c.list(), "items", []) or [])
    seed = next((b for b in boxes if getattr(b, "status", "") in ("placing", "restoring", "running")), None)
    if seed:
        break
    time.sleep(20)
if not seed:
    print("NO_SEED: no build box found in ~10min")
    raise SystemExit(0)

print(f"seed={seed.id} status={seed.status}; probing hogpanion via exec...", flush=True)
last = ""
for i in range(40):  # ~13min of probing
    b = c.get(seed.id)
    if b.status == "running":
        print(f"RUNNING: build proceeding (hogpanion up + bootstrap done) after ~{i*20}s")
        raise SystemExit(0)
    if b.status == "failed":
        print(f"FAILED: {getattr(b.view,'fail_reason','')!r}")
        raise SystemExit(0)
    try:
        r = b.exec(["true"], timeout_seconds=10)
        print(f"HOGPANION_UP: exec ok on {seed.id} (status={b.status}) → bootstrap is running, build should proceed")
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        last = type(e).__name__ + ": " + str(e)[:160]
    time.sleep(20)
print(f"NO_EARLY_SIGNAL after ~13min (exec gated during placing or hogpanion down). last_exec_err={last}")
