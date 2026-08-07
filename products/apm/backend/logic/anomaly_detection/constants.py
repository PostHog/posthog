"""Fixed grid constants. The 5-minute UTC bucket grid is architectural
(bucket identities must stay stable across ticks, backfills, and recomputes),
so unlike the dials in config.py these are not env-tunable.
"""

BUCKET_MINUTES = 5
BUCKETS_PER_HOUR = 60 // BUCKET_MINUTES
BUCKETS_PER_DAY = 24 * BUCKETS_PER_HOUR
BUCKETS_PER_WEEK = 7 * BUCKETS_PER_DAY
