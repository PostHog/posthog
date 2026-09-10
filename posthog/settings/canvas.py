import os

from posthog.settings.base_variables import BASE_DIR, TEST
from posthog.settings.utils import get_from_env, get_list

CANVAS_ARTIFACT_ORIGIN = os.getenv("CANVAS_ARTIFACT_ORIGIN", "").rstrip("/")
# Optional dedicated keys. Artifact signing otherwise uses SECRET_KEY and its
# fallbacks, so enabling the artifact origin does not require a second secret.
CANVAS_ARTIFACT_SIGNING_KEYS = get_list(os.getenv("CANVAS_ARTIFACT_SIGNING_KEYS", ""))
if TEST and not CANVAS_ARTIFACT_SIGNING_KEYS:
    CANVAS_ARTIFACT_SIGNING_KEYS = ["canvas-artifact-development-key-32-bytes"]

# When > 0, artifact responses are `public` with this `s-maxage`, so a CDN in
# front of CANVAS_ARTIFACT_ORIGIN can cache them. Artifacts are immutable and
# content-addressed, and the cache key is the full URL (signed token included),
# so this bounds only how long a shared cache may keep serving a URL after its
# token expires. 0 (the default) keeps responses `private` (browser-only).
CANVAS_ARTIFACT_SHARED_CACHE_SECONDS = get_from_env("CANVAS_ARTIFACT_SHARED_CACHE_SECONDS", 0, type_cast=int)

# The canvas builder package (build.mjs + manifest.json + npm lockfile). A
# settings constant rather than an import so the tasks product can bake it
# into the CANVAS_BUILD sandbox image without a tasks → canvas dependency.
CANVAS_BUILDER_DIR = os.path.join(BASE_DIR, "products", "canvas", "packages", "canvas_builder")
