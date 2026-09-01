import os

from posthog.settings.base_variables import CLOUD_DEPLOYMENT, DEBUG, TEST
from posthog.settings.utils import get_list, get_set

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
SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS: set[str] = get_set(
    os.getenv("SIGNALS_LIGHTHOUSE_ALLOWED_HOSTS", "posthog.com,www.posthog.com")
)

# Teams whose scouts may spend an audit. Defaults to the deployment's own internal project — the
# same team split the usage report uses — so the capability reaches us and nobody else. A page on
# the host allowlist is public either way; this bounds who can spend the Browserless quota on it.
_DEFAULT_LIGHTHOUSE_TEAM_ID = "1" if (CLOUD_DEPLOYMENT or "").upper() == "EU" else "2"
SIGNALS_LIGHTHOUSE_TEAM_IDS: set[int] = {
    int(team_id) for team_id in get_set(os.getenv("SIGNALS_LIGHTHOUSE_TEAM_IDS", _DEFAULT_LIGHTHOUSE_TEAM_ID))
}
