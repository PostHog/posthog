"""List my boxes on dev and destroy any orphaned seed/preview boxes."""
import sys

from hog import client

c = client()
boxes = c.list()
items = getattr(boxes, "items", boxes)
items = list(items) if items else []
print(f"{len(items)} box(es):", flush=True)
for b in items:
    spec = b.spec
    print(f"  {b.id}  status={b.status}  cpus={getattr(spec,'cpus','?')}  mem={getattr(spec,'memory_mib','?')}  name={getattr(b,'name',None)}", flush=True)

# Destroy anything passed as argv (box ids), or all if --all.
to_kill = sys.argv[1:]
if to_kill == ["--all"]:
    to_kill = [b.id for b in items]
for bid in to_kill:
    c.get(bid).destroy()
    print(f"destroyed {bid}", flush=True)
