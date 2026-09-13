COORDINATOR_INTERVAL_MINUTES = 15
# Per-team baselines are relearned once a day; the detect child does it when its rows are older.
BASELINE_REFRESH_MINUTES = 24 * 60
BASELINE_SAMPLE_WINDOW_DAYS = 30
# Fewer than this many days of history and the learned bar is noise; only the requester guard runs.
BASELINE_MIN_HISTORY_DAYS = 14

# Teams past this cap roll to the next tick: each tick takes the next page of them, wrapping at
# the end, so a large fleet is covered over several ticks rather than the same teams every time.
MAX_TEAMS_PER_RUN = 200

MASTER_FLAG = "product-support-ticket-patterns"
