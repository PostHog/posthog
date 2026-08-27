import os

from posthog.settings.base_variables import BASE_DIR, DEBUG, TEST
from posthog.settings.utils import get_list

CANVAS_ARTIFACT_ORIGIN = os.getenv("CANVAS_ARTIFACT_ORIGIN", "").rstrip("/")
CANVAS_ARTIFACT_SIGNING_KEYS = get_list(os.getenv("CANVAS_ARTIFACT_SIGNING_KEYS", ""))
# DEBUG and TEST fall back to a fixed key so published canvases render with no
# manual env setup; artifacts.py already refuses these modes' shortcuts in
# production (boot check + host enforcement).
if (TEST or DEBUG) and not CANVAS_ARTIFACT_SIGNING_KEYS:
    CANVAS_ARTIFACT_SIGNING_KEYS = ["canvas-artifact-development-key-32-bytes"]

# The canvas builder package (build.mjs + manifest.json + npm lockfile). A
# settings constant rather than an import so the tasks product can bake it
# into the CANVAS_BUILD sandbox image without a tasks → canvas dependency.
CANVAS_BUILDER_DIR = os.path.join(BASE_DIR, "products", "canvas", "packages", "canvas_builder")
