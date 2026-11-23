import re
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.event_definition_generators.base import EventDefinitionGenerator
from posthog.api.event_definition_generators.golang import GolangGenerator, GoSDK
from posthog.api.event_definition_generators.python import PythonGenerator
from posthog.api.event_definition_generators.test.database_inputs import database_inputs
from posthog.api.event_definition_generators.typescript import TypeScriptGenerator, TypeScriptTypesGenerator

SNAPSHOTS = Path(__file__).parent / "snapshots"


class TestDatabaseOutputIsUnchanged(SimpleTestCase):
    # The snapshots were written by the generators before they learned to render enums and
    # descriptions from a stack description. Inputs shaped like database rows, descriptions
    # included, must still give exactly the same modules.
    @parameterized.expand(
        [
            ("python.py", PythonGenerator()),
            ("golang.go", GolangGenerator()),
            ("golang_v2.go", GolangGenerator(GoSDK.POSTHOG_GO_V2)),
            ("typescript.ts", TypeScriptGenerator()),
            ("typescript_types.ts", TypeScriptTypesGenerator()),
        ]
    )
    def test_generated_module_matches_snapshot(self, snapshot: str, generator: EventDefinitionGenerator):
        events, schema_map = database_inputs()
        generated = re.sub(r"Generated at: \S+", "Generated at: <time>", generator.generate(events, schema_map))  # type: ignore[arg-type]

        self.assertEqual(generated, (SNAPSHOTS / f"{snapshot}.snapshot").read_text())
