# /// script
# requires-python = ">=3.14"
# dependencies = ["hoglint==0.2.5", "django==6.1.3"]
# ///
"""Run the pinned Hoglint with this script's arguments.

turbo-discover.js and trunk-impacted-targets.js run
`hoglint_run.py watched --level isolated --out <file> --map <file>` with `uv run --no-project` from
the repo root, so they need uv and nothing from the Python project.
One process writes both answers: each product's Isolated verdict and watched files (JSON), and the
file-level import map ({file: [files that import it]}).

The Hoglint pin above is the one in the dev group of pyproject.toml, so the answers come from the
same Hoglint that CI's `hoglint compare` runs. Hoglint's Django pack reads Django's own source to
find the repo's models, and Hoglint reads third-party source only from its interpreter's
site-packages, so Django is a dependency here too, at the version uv.lock locks. Without it
`hoglint watched` answers `complete: false` and every product loses its skip.
"""

import sys
import runpy

sys.argv = ["hoglint", *sys.argv[1:]]
runpy.run_module("hoglint", run_name="__main__")
