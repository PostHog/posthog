"""Fixed grid constants. The 5-minute UTC bucket grid is architectural
(bucket identities must stay stable across ticks, backfills, and recomputes),
so unlike the dials in anomaly_detection/config.py these are not env-tunable.

Lives outside the anomaly_detection package because that package's __init__
re-exports the detector (numpy, scipy): consumers that need only the grid —
schedulers, Temporal workers — must be able to import it without paying for
the detector.
"""

BUCKET_MINUTES = 5
BUCKETS_PER_HOUR = 60 // BUCKET_MINUTES
BUCKETS_PER_DAY = 24 * BUCKETS_PER_HOUR
BUCKETS_PER_WEEK = 7 * BUCKETS_PER_DAY
