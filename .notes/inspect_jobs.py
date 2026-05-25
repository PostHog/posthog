"""Print PreaggregationJob rows for team 37 with timing info."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django

django.setup()

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob

rows = (
    PreaggregationJob.objects.filter(team_id=37)
    .order_by("time_range_start", "created_at")
    .values("id", "query_hash", "time_range_start", "time_range_end", "status", "created_at", "computed_at")
)

prev_range = None
for r in rows:
    rng = (r["time_range_start"], r["time_range_end"])
    marker = "  ↳ " if rng == prev_range else "    "
    computed = r["computed_at"].isoformat() if r["computed_at"] else "—"
    insert_dur = (
        (r["computed_at"] - r["created_at"]).total_seconds() if r["computed_at"] else None
    )
    print(
        f"{marker}{r['time_range_start'].date()} → {r['time_range_end'].date()}"
        f"  status={r['status']:8s}"
        f"  created={r['created_at'].isoformat()}"
        f"  insert_dur={f'{insert_dur:.3f}s' if insert_dur is not None else '—'}"
        f"  id={str(r['id'])[:8]}"
    )
    prev_range = rng
