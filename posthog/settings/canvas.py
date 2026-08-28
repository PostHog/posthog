import os

from posthog.settings.base_variables import BASE_DIR, TEST
from posthog.settings.utils import get_list

CANVAS_ARTIFACT_ORIGIN = os.getenv("CANVAS_ARTIFACT_ORIGIN", "").rstrip("/")
CANVAS_ARTIFACT_SIGNING_KEYS = get_list(os.getenv("CANVAS_ARTIFACT_SIGNING_KEYS", ""))
if TEST and not CANVAS_ARTIFACT_SIGNING_KEYS:
    CANVAS_ARTIFACT_SIGNING_KEYS = ["canvas-artifact-development-key-32-bytes"]

# The canvas builder package (build.mjs + manifest.json + npm lockfile). A
# settings constant rather than an import so the tasks product can bake it
# into the CANVAS_BUILD sandbox image without a tasks → canvas dependency.
CANVAS_BUILDER_DIR = os.path.join(BASE_DIR, "products", "canvas", "packages", "canvas_builder")
