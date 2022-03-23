import os

from posthog.settings.utils import get_list

# These flags will be force-enabled on the frontend
# The features here are released, but the flags are just not yet removed from the code
# To ignore this persisted feature flag behavior, set `PERSISTED_FEATURE_FLAGS = 0`
PERSISTED_FEATURE_FLAGS = get_list(os.getenv("PERSISTED_FEATURE_FLAGS", "")) + [
    # Add hard-coded feature flags for static self-hosted releases here
    "invite-teammates-prompt",
    "insight-legends",
]
