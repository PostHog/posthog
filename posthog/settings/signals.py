import os

from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_list

# Signs the per-delivery map of already-rendered chart assets that scout Slack delivery keeps in the
# shared Redis, so a process able to write that Redis cannot swap in another asset id. Dedicated and
# rotatable rather than SECRET_KEY, which is fleet-wide and backs session/CSRF signing: give this
# comma-separated `new_key,old_key`, and the first key signs while every key verifies. Unset outside
# dev/test means no reuse — a retry re-renders the charts rather than trusting an unverifiable entry.
SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS: list[str] = get_list(os.getenv("SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS", ""))
if (TEST or DEBUG) and not SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS:
    SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS = ["signals-slack-chart-cache-development-key"]
