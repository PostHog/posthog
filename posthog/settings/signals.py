import os

from posthog.settings.base_variables import CLOUD_DEPLOYMENT, DEBUG, TEST
from posthog.settings.utils import get_list, get_set, parse_team_ids

# Signs the per-delivery map of already-rendered chart assets that scout Slack delivery keeps in the
# shared Redis, so a process able to write that Redis cannot swap in another asset id. Dedicated and
# rotatable rather than SECRET_KEY, which is fleet-wide and backs session/CSRF signing: give this
# comma-separated `new_key,old_key`, and the first key signs while every key verifies. Unset outside
# dev/test means no reuse — a retry re-renders the charts rather than trusting an unverifiable entry.
SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS: list[str] = get_list(os.getenv("SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS", ""))
if (TEST or DEBUG) and not SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS:
    SIGNALS_SLACK_CHART_CACHE_SIGNING_KEYS = ["signals-slack-chart-cache-development-key"]

# Hosts a scout may point a Lighthouse audit at. An audit drives a real browser at a real page, so
# this is an allowlist and not a blocklist. It holds our own marketing and docs site, which is
# public: no credential ever has to reach the headless browser. The app hosts are absent on
# purpose — the browser signs in to nothing, so an app URL would measure the login screen and
# report its LCP as the page's.
# Lower-cased at parse time because the check compares against a lower-cased hostname; an operator
# who writes `PostHog.com` would otherwise get a set that silently matches nothing.
SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS: set[str] = {
    host.lower() for host in get_set(os.getenv("SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS", "posthog.com,www.posthog.com"))
}

# Teams whose scouts may spend an audit. Defaults to the deployment's own internal project on
# PostHog Cloud — the same team split the usage report uses — and to NOBODY anywhere else. Off
# Cloud, "team 2" is an arbitrary customer project rather than ours, and `LIGHTHOUSE_BROWSERLESS_URL`
# falls back to the heatmap fleet, so a region-shaped default would hand the capability to any
# self-hosted install that had configured Browserless for screenshots. Enabling it there is an
# explicit act: set this variable.
_DEFAULT_LIGHTHOUSE_TEAM_IDS = {"EU": "1", "US": "2"}.get((CLOUD_DEPLOYMENT or "").upper(), "")


SIGNALS_LIGHTHOUSE_TEAM_IDS: set[int] = parse_team_ids(
    os.getenv("SIGNALS_LIGHTHOUSE_TEAM_IDS", _DEFAULT_LIGHTHOUSE_TEAM_IDS)
)
