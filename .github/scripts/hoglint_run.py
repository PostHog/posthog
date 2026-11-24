# /// script
# requires-python = ">=3.14"
# dependencies = ["hoglint==0.2.4"]
# ///
"""Run the pinned hoglint with this script's arguments.

turbo-discover.js and trunk-impacted-targets.js run `hoglint_run.py map` with `uv run --no-project`
from the repo root, so they need uv and nothing from the Python project. One runner serves every
hoglint command a CI script needs. The hoglint pin above is the one in the dev group of
pyproject.toml, so the answers come from the same hoglint that CI's `hoglint compare` runs.
"""

import sys
import runpy

sys.argv = ["hoglint", *sys.argv[1:]]
runpy.run_module("hoglint", run_name="__main__")
