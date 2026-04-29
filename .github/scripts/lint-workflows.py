#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "click>=8.0"]
# ///
# ruff: noqa: T201 allow print statements
"""CI entrypoint for the workflow lint framework.

Replaces the per-rule scripts that previously lived alongside this one:

- check-ci-timeouts.py
- check-ci-concurrency.py
- check-dorny-paths-filter.py
- check-semgrep-services-coverage.py

The actual rule definitions and runner live in
``tools/hogli-commands/hogli_commands/workflow_lint/``. Locally, run via
``bin/hogli lint:workflows``.

This thin entrypoint exists because the full ``bin/hogli`` requires a synced
project venv (``uv sync --frozen``), which is overkill for one CI job. The
inline-script header above makes ``uv run`` self-contained — same shape as
the four scripts it replaces.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOGLI_COMMANDS_DIR = REPO_ROOT / "tools" / "hogli-commands" / "hogli_commands"

# Stub the ``hogli_commands`` parent package so that importing
# ``hogli_commands.workflow_lint`` does not trigger the real package's
# ``__init__.py`` (which transitively imports posthog deps we don't have in
# the minimal CI venv). The synthetic package's ``__path__`` points at the
# directory so submodule resolution still works.
_stub = types.ModuleType("hogli_commands")
_stub.__path__ = [str(HOGLI_COMMANDS_DIR)]  # type: ignore[attr-defined]
sys.modules.setdefault("hogli_commands", _stub)

from hogli_commands.workflow_lint.cli import cmd_lint_workflows  # noqa: E402

if __name__ == "__main__":
    cmd_lint_workflows.main(prog_name="lint:workflows", standalone_mode=True)
