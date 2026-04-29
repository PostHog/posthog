"""Keep posthog/rbac/_generated_guest_overridable.py in sync with schema.json.

If a future TypeScript change adds or removes @guestOverridable annotations and
the developer forgets to run `bin/build-schema-python.sh`, this test fails and
points them to the regen command. Runs the generator in-process against the
current schema.json and compares the output to what's committed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from posthog.test.base import BaseTest

from posthog.rbac._generated_guest_overridable import GUEST_OVERRIDABLE_FIELDS

ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = ROOT / "bin" / "generate-guest-overridable.py"
SCHEMA_JSON = ROOT / "frontend" / "src" / "queries" / "schema.json"


def _load_generator_module():
    # The generator script sits under bin/ with a dash in its filename, so we
    # import it via importlib rather than a normal `import bin.generate...`.
    spec = importlib.util.spec_from_file_location("_guest_overridable_generator", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGeneratedWhitelistInSync(BaseTest):
    def test_committed_whitelist_matches_schema_json(self) -> None:
        import json

        generator = _load_generator_module()
        with SCHEMA_JSON.open() as f:
            schema = json.load(f)
        expected = generator.collect_overridable_fields(schema)

        # `expected` has frozenset values — same shape as the committed module.
        self.assertEqual(
            GUEST_OVERRIDABLE_FIELDS,
            expected,
            "posthog/rbac/_generated_guest_overridable.py is out of sync with "
            "frontend/src/queries/schema.json. Run `bin/build-schema-python.sh` "
            "(or `python3 bin/generate-guest-overridable.py`) to regenerate.",
        )
