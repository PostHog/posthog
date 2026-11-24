"""Project CLI_NOTICES from posthog/cli_notices.py into hog/release/notices.generated.json.

Every hog release copies the generated file into its manifest, and the PostHog API sends the same
list in a header, so one list reaches every hog both ways.

Registered in `tools/hogli-commands/hogli_commands/projections.py`; run `hogli build:projections`.
"""

from __future__ import annotations

import sys
import json
import importlib.util
from pathlib import Path
from types import ModuleType

NOTICES_MODULE = Path(__file__).resolve().parent / "cli_notices.py"
_STANDALONE_MODULE_NAME = "_posthog_cli_notices_standalone"
OUTPUT = "hog/release/notices.generated.json"


# `import posthog.cli_notices` runs posthog/__init__.py, which sets up Celery and Django settings.
def _load_notices_without_django() -> ModuleType:
    if _STANDALONE_MODULE_NAME not in sys.modules:
        spec = importlib.util.spec_from_file_location(_STANDALONE_MODULE_NAME, NOTICES_MODULE)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load {NOTICES_MODULE}")
        module = importlib.util.module_from_spec(spec)
        # dataclasses resolves the module of each class through sys.modules while it builds the class.
        sys.modules[_STANDALONE_MODULE_NAME] = module
        spec.loader.exec_module(module)
    return sys.modules[_STANDALONE_MODULE_NAME]


def render() -> dict[str, str]:
    notices = _load_notices_without_django().CLI_NOTICES
    ids = [notice.id for notice in notices]
    repeated = sorted({notice_id for notice_id in ids if ids.count(notice_id) > 1})
    if repeated:
        raise ValueError(f"CLI_NOTICES names {', '.join(repeated)} more than once")
    return {OUTPUT: json.dumps({"notices": [notice.as_item() for notice in notices]}, indent=4) + "\n"}
