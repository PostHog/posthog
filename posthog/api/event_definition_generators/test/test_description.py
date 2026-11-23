import os
import sys
import json
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import time_machine

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.event_definition_generators.description import (
    DescribedProperty,
    generate_from_description,
    schema_from_description,
    schema_hash_from_description,
)
from posthog.api.event_definition_generators.golang import GO_SDK_IMPORT_PATHS, GolangGenerator, GoSDK
from posthog.api.event_definition_generators.python import PythonGenerator
from posthog.api.event_definition_generators.typescript import TypeScriptGenerator

FIXTURE = Path(__file__).parents[4] / "packages/sdk/tests/fixtures/stack-all-kinds/description.json"


class TestSchemaFromDescription(SimpleTestCase):
    def setUp(self):
        self.description = json.loads(FIXTURE.read_text())

    def test_events_carry_their_group_properties_with_types_requirements_enums_and_descriptions(self):
        schema = schema_from_description(self.description)

        self.assertEqual([event.name for event in schema.event_definitions], ["checkout_completed", "plan_upgraded"])
        self.assertEqual(
            schema.schema_map["checkout_completed"],
            [
                DescribedProperty(
                    name="account_id",
                    property_type="String",
                    is_required=True,
                    is_optional_in_types=False,
                    description="",
                    enum=None,
                ),
                DescribedProperty(
                    name="order_id",
                    property_type="String",
                    is_required=True,
                    is_optional_in_types=False,
                    description="",
                    enum=None,
                ),
                DescribedProperty(
                    name="paid_at",
                    property_type="DateTime",
                    is_required=False,
                    is_optional_in_types=False,
                    description="",
                    enum=None,
                ),
                DescribedProperty(
                    name="plan",
                    property_type="String",
                    is_required=False,
                    is_optional_in_types=False,
                    description="",
                    enum=("free", "team", "scale"),
                ),
                DescribedProperty(
                    name="total_usd",
                    property_type="Numeric",
                    is_required=True,
                    is_optional_in_types=False,
                    description="Order total after discounts",
                    enum=None,
                ),
            ],
        )

    def test_a_ref_to_a_group_the_description_lacks_is_an_error(self):
        broken = {
            "version": 1,
            "resources": [
                {
                    "kind": "event",
                    "key": "signed_up",
                    "body": {
                        "name": "signed_up",
                        "property_groups": [{"$ref": {"kind": "property_group", "key": "gone"}}],
                    },
                }
            ],
        }

        with self.assertRaisesMessage(ValueError, "signed_up"):
            schema_from_description(broken)

    def test_the_schema_hash_follows_the_properties(self):
        before = schema_hash_from_description(PythonGenerator(), self.description)
        group = next(
            r for r in self.description["resources"] if r["kind"] == "property_group" and r["key"] == "plan_upgraded"
        )
        group["body"]["properties"][0]["is_required"] = False

        self.assertNotEqual(before, schema_hash_from_description(PythonGenerator(), self.description))


class TestGeneratorsFromDescription(SimpleTestCase):
    def setUp(self):
        self.description = json.loads(FIXTURE.read_text())

    @parameterized.expand(
        [("python", PythonGenerator), ("golang", GolangGenerator), ("typescript", TypeScriptGenerator)]
    )
    def test_a_module_is_the_same_for_the_same_description(self, _name, generator):
        # `hog stack generate --check` compares the file with a module generated now, so the time cannot be in it.
        with time_machine.travel("2026-01-01T00:00:00", tick=False):
            first = generate_from_description(generator(), self.description)
        with time_machine.travel("2026-06-01T00:00:00", tick=False):
            second = generate_from_description(generator(), self.description)

        self.assertEqual(first, second)
        self.assertIn(schema_hash_from_description(generator(), self.description), first)

    def test_python_module_imports_and_types_each_capture_method(self):
        # The generated module imports the posthog SDK, whose package name this repository's own
        # package shadows, so it runs in a fresh interpreter next to a minimal stand-in for the SDK.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "posthog").mkdir()
            (root / "posthog" / "__init__.py").write_text(
                "class Posthog:\n    def capture(self, event, **kwargs):\n        return event\n"
            )
            (root / "posthog" / "args.py").write_text(
                "from typing import TypedDict\n\nclass OptionalCaptureArgs(TypedDict, total=False):\n    distinct_id: str\n"
            )
            (root / "posthog_typed.py").write_text(generate_from_description(PythonGenerator(), self.description))
            script = (
                "import inspect, json, posthog_typed\n"
                "client = posthog_typed.PosthogTyped\n"
                "signature = inspect.signature(client.capture_checkout_completed)\n"
                "print(json.dumps({name: [str(p.annotation), p.default is inspect.Parameter.empty]"
                " for name, p in signature.parameters.items() if name not in ('self', 'kwargs', 'extra_properties')}))\n"
            )
            run = subprocess.run(
                [sys.executable, "-c", script],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                env={"PATH": os.environ.get("PATH", "")},
            )

        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            json.loads(run.stdout),
            {
                "account_id": ["<class 'str'>", True],
                "order_id": ["<class 'str'>", True],
                "total_usd": ["<class 'float'>", True],
                "paid_at": [str(Optional[datetime]), False],
                "plan": [str(Optional[Literal["free", "team", "scale"]]), False],
            },
        )

    def test_typescript_module_types_each_event(self):
        code = generate_from_description(TypeScriptGenerator(), self.description)

        self.assertIn(
            "    /** A customer paid for an order. Sent by the server after the payment provider confirms. */\n"
            '    "checkout_completed": {\n'
            '        "account_id": string\n'
            '        "order_id": string\n'
            '        "paid_at"?: string | Date\n'
            '        "plan"?: "free" | "team" | "scale"\n'
            "        /** Order total after discounts */\n"
            '        "total_usd": number\n'
            "    }",
            code,
        )
        self.assertIn('        "from_plan": "free" | "team"\n', code)

    def test_python_docstring_carries_the_property_descriptions(self):
        code = generate_from_description(PythonGenerator(), self.description)

        self.assertIn("        Args:\n            total_usd: Order total after discounts\n", code)

    def test_go_module_compiles_with_required_properties_as_parameters(self):
        module_path = GO_SDK_IMPORT_PATHS[GoSDK.POSTHOG_GO]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # A local stand-in for posthog-go, so the compiler needs no network.
            (root / "posthog-go").mkdir()
            (root / "posthog-go" / "go.mod").write_text(f"module {module_path}\n\ngo 1.21\n")
            (root / "posthog-go" / "posthog.go").write_text(
                "package posthog\n\n"
                "type Properties map[string]interface{}\n\n"
                "func (p Properties) Merge(other Properties) Properties {\n"
                "\tresult := Properties{}\n\tfor k, v := range p {\n\t\tresult[k] = v\n\t}\n"
                "\tfor k, v := range other {\n\t\tresult[k] = v\n\t}\n\treturn result\n}\n\n"
                "type Capture struct {\n\tDistinctId string\n\tEvent      string\n\tProperties Properties\n}\n"
            )
            (root / "go.mod").write_text(
                f"module testmodule\n\ngo 1.21\n\nrequire {module_path} v0.0.0\n\nreplace {module_path} => ./posthog-go\n"
            )
            (root / "typed").mkdir()
            (root / "typed" / "events.go").write_text(generate_from_description(GolangGenerator(), self.description))
            (root / "main.go").write_text(
                "package main\n\n"
                'import (\n\t"time"\n\t"testmodule/typed"\n)\n\n'
                "func main() {\n"
                '\t_ = typed.CheckoutCompletedCapture("user", "account", "order", 12.5,\n'
                "\t\ttyped.CheckoutCompletedWithPaidAt(time.Now()),\n"
                "\t\ttyped.CheckoutCompletedWithPlan(typed.CheckoutCompletedPlanTeam),\n\t)\n"
                '\t_ = typed.PlanUpgradedCapture("user", "account", typed.PlanUpgradedFromPlanFree, typed.PlanUpgradedWithTrial(true))\n'
                "\tvar plans = []typed.CheckoutCompletedPlan{typed.CheckoutCompletedPlanFree, typed.CheckoutCompletedPlanScale}\n"
                "\t_ = plans\n"
                "}\n"
            )

            build = subprocess.run(
                ["go", "build", "-o", "check", "main.go"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "GOPROXY": "off", "GOFLAGS": "-mod=mod"},
            )

        self.assertEqual(build.returncode, 0, build.stderr)
