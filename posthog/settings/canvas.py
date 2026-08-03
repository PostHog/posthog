import os

from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_list

CANVAS_ARTIFACT_ORIGIN = os.getenv("CANVAS_ARTIFACT_ORIGIN", "").rstrip("/")
CANVAS_ARTIFACT_SIGNING_KEYS = get_list(os.getenv("CANVAS_ARTIFACT_SIGNING_KEYS", ""))
if (DEBUG or TEST) and not CANVAS_ARTIFACT_SIGNING_KEYS:
    CANVAS_ARTIFACT_SIGNING_KEYS = ["canvas-artifact-development-key-32-bytes"]
