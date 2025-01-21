from datetime import timedelta

"""
Utilities used by the insights API to determine whether
or not to refresh an insight upon a client request to do so
"""


# Default minimum wait time for refreshing an insight
BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=15)
# Wait time for short-term insights
REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=3)
# Wait time for "real-time" insights
REAL_TIME_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=1)
