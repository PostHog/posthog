"""Exported grid constants for apm.

A lightweight import path for consumers that need only the detection grid:
``facade/api.py`` also re-exports these, but importing it pulls the full
detector (numpy, scipy) along, which schedulers and workers must not pay
for one integer.
"""

from products.apm.backend.logic.grid import BUCKET_MINUTES, BUCKETS_PER_DAY, BUCKETS_PER_HOUR, BUCKETS_PER_WEEK

__all__ = [
    "BUCKET_MINUTES",
    "BUCKETS_PER_DAY",
    "BUCKETS_PER_HOUR",
    "BUCKETS_PER_WEEK",
]
