# /// script
# requires-python = ">=3.14"
# dependencies = ["hoglint==0.2.4"]
# ///
"""Print hoglint's file-level import map ({file: [files that import it]}) as JSON on stdout.

turbo-discover.js and trunk-impacted-targets.js run this with `uv run --no-project` from the
repo root, so they need uv and nothing from the Python project. `hoglint map` reads hoglint.toml
and runs no rule, pack or provider. The hoglint pin above is the one in the dev group of
pyproject.toml, so the map comes from the same hoglint that CI's `hoglint compare` runs.
"""

import sys
import runpy

sys.argv = ["hoglint", "map"]
runpy.run_module("hoglint", run_name="__main__")
