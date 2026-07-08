import os

from posthog.settings.base_variables import BASE_DIR
from posthog.settings.utils import get_from_env

GEOIP_PATH = os.path.join(BASE_DIR, "share")

# Temporary (June 2026 MaxMind incident: https://posthog.slack.com/archives/C0B9DDSCTF1): enables the query-time geoip
# dict fallback for a comma-separated list of team ids, or "*" for all teams. Empty (the default) disables it
# everywhere. Remove with the fallback.
HOGQL_GEOIP_DICT_FALLBACK_TEAMS = get_from_env("HOGQL_GEOIP_DICT_FALLBACK_TEAMS", "")
