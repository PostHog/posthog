import os

from posthog.settings.base_variables import BASE_DIR
from posthog.settings.utils import get_from_env, str_to_bool

GEOIP_PATH = os.path.join(BASE_DIR, "share")

# Temporary (June 2026 MaxMind incident): instance-wide default for HogQLQueryModifiers.useGeoipDictFallback, so the
# query-time geoip fallback can be enabled per region without touching every team. Remove with the fallback.
HOGQL_GEOIP_DICT_FALLBACK = get_from_env("HOGQL_GEOIP_DICT_FALLBACK", False, type_cast=str_to_bool)
