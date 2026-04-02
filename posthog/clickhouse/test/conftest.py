"""Pytest conftest — loads Django/ClickHouse stubs before test modules are imported.

This replaces the importlib.util bootstrap that was duplicated across every
test file in this directory.  Stubs install themselves on load and are
idempotent, so re-importing _stubs in a test file is safe but unnecessary.
"""

from __future__ import annotations

import os
import sys
import importlib.util

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

_spec = importlib.util.spec_from_file_location(
    "posthog.clickhouse.test._stubs",
    os.path.join(_BASE, "posthog", "clickhouse", "test", "_stubs.py"),
)
assert _spec and _spec.loader
_stubs_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stubs_mod)
