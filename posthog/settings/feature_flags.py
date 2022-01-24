import os
from typing import List

from posthog.settings.base_variables import DEBUG, E2E_TESTING
from posthog.settings.utils import get_list

# These flags will be force-enabled on the frontend **and OVERRIDE all** flags from `/decide`
# The features here are released, but the flags are just not yet removed from the code.
# To ignore this persisted feature flag behavior, set `PERSISTED_FEATURE_FLAGS = 0`
env_feature_flags = os.getenv("PERSISTED_FEATURE_FLAGS", "")
PERSISTED_FEATURE_FLAGS: List[str] = []
default_flag_persistence = [
    # Add hard-coded feature flags for static self-hosted releases here
    "new-paths-ui-edge-weights",
    "5730-funnel-horizontal-ui",
    "insight-legends",
]

if env_feature_flags != "0" and env_feature_flags.lower() != "false" and not DEBUG and not E2E_TESTING:
    PERSISTED_FEATURE_FLAGS = default_flag_persistence + get_list(env_feature_flags)
