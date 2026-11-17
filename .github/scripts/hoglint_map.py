# /// script
# requires-python = ">=3.14"
# dependencies = ["hoglint==0.2.1"]
# ///
"""Run the pinned hoglint with this script's arguments.

turbo-discover.js and trunk-impacted-targets.js run `hoglint_map.py watched --out <file> --map <file>`
with `uv run --no-project` from the repo root, so they need uv and nothing from the Python project.
One process writes both answers: each product's watched files and Isolated verdict (JSON), and the
file-level import map ({file: [files that import it]}). `hoglint watched` reads hoglint.toml and runs
every rule. The hoglint pin above is the one in the dev group of pyproject.toml, so the answers come
from the same hoglint that CI's `hoglint compare` runs.
"""

import sys
import runpy

sys.argv = ["hoglint", *sys.argv[1:]]
runpy.run_module("hoglint", run_name="__main__")
