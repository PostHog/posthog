# /// script
# requires-python = ">=3.11"
# dependencies = ["tach==0.34.1"]
# ///
"""Print tach's file-level import map ({file: [files that import it]}) as JSON on stdout.

turbo-discover.js and trunk-impacted-targets.js run this with `uv run --no-project` from the
repo root, so they need uv and nothing from the Python project. The tach pin above is the one
uv.lock carries, so the map comes from the same tach that `tach check` runs in ci-backend.
"""

import sys

from tach.start import start

sys.argv = ["tach", "map", "--direction", "dependents", "--output", "-"]
start()
