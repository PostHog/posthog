import os
from typing import List

from posthog.settings.base_variables import DEBUG
from posthog.settings.utils import get_list

# These flags will be force-enabled on the frontend **and OVERRIDE all** flags from `/decide`
# The features here are released, but the flags are just not yet removed from the code.
# To ignore this persisted feature flag behavior, set `PERSISTED_FEATURE_FLAGS = 0`
env_feature_flags = os.getenv("PERSISTED_FEATURE_FLAGS", "")
PERSISTED_FEATURE_FLAGS: List[str] = []
default_flag_persistence = [
    # Add hard-coded feature flags for static self-hosted releases here
    "5440-multivariate-support",
    "new-paths-ui-edge-weights",
    "new-sessions-player-events-list",
    "session-insight-removal",
    "funnel-simple-mode",
]

if env_feature_flags != "0" and env_feature_flags.lower() != "false" and not DEBUG:
    PERSISTED_FEATURE_FLAGS = default_flag_persistence + get_list(env_feature_flags)
