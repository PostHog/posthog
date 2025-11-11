"""
Integration test for TypeScript definition generation.

Tests the complete flow:
1. Create EventDefinitions with EventSchemas
2. Generate TypeScript via the typescript_definitions method
3. Write generated TypeScript to temp file
4. Create a test file that uses the types
5. Run TypeScript compiler to verify no errors
"""

import tempfile
import subprocess
from pathlib import Path

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import EventDefinition, EventSchema, SchemaPropertyGroup, SchemaPropertyGroupProperty


class TestEventDefinitionTypeScriptGeneration(APIBaseTest):
    """
    Critical integration test ensuring TypeScript generation maintains type safety
    while allowing additional properties beyond the schema.
    """

    def setUp(self):
        super().setUp()

        # Create property group with required and optional fields
        self.property_group = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="Test Properties"
        )

        SchemaPropertyGroupProperty.objects.create(
            property_group=self.property_group,
            name="required_field",
            property_type="Numeric",
            is_required=True,
            description="A required numeric field",
        )

        SchemaPropertyGroupProperty.objects.create(
            property_group=self.property_group,
            name="optional_field",
            property_type="String",
            is_required=False,
            description="An optional string field",
        )

        # Create event definition and link to property group
        self.event_def = EventDefinition.objects.create(team=self.team, project=self.project, name="test_event")

        EventSchema.objects.create(event_definition=self.event_def, property_group=self.property_group)

        # Create event with all optional fields
        self.optional_event_def = EventDefinition.objects.create(
            team=self.team, project=self.project, name="optional_event"
        )

        optional_property_group = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="Optional Properties"
        )

        SchemaPropertyGroupProperty.objects.create(
            property_group=optional_property_group,
            name="optional_only",
            property_type="String",
            is_required=False,
        )

        EventSchema.objects.create(event_definition=self.optional_event_def, property_group=optional_property_group)

        # Create event with no schema (all properties allowed)
        self.untyped_event_def = EventDefinition.objects.create(
            team=self.team, project=self.project, name="untyped_event"
        )

        # Create event with special characters to test escaping
        self.special_chars_event = EventDefinition.objects.create(
            team=self.team, project=self.project, name="a'a\\'b\"c>?>%}}%%>c<[[?${{%}}cake'"
        )

        special_property_group = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="Special Properties"
        )

        SchemaPropertyGroupProperty.objects.create(
            property_group=special_property_group,
            name="prop'with\\'quotes\"\\slash",
            property_type="String",
            is_required=True,
        )

        EventSchema.objects.create(event_definition=self.special_chars_event, property_group=special_property_group)

    def _generate_typescript(self) -> str:
        """Generate TypeScript definitions by calling the actual API endpoint"""
        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/typescript/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()["content"]

    def test_typescript_allows_additional_properties(self):
        """
        Critical test: Verify that additional properties beyond schema
        are allowed while required properties are still validated.

        This is the core functionality that prevents "excess property checking"
        errors in TypeScript while maintaining type safety for required fields.

        Uses the real posthog-js package to ensure compatibility with actual types.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Generate TypeScript
            ts_content = self._generate_typescript()

            # Create minimal package.json to install only required dependencies
            package_json = tmpdir_path / "package.json"
            package_json.write_text('{"dependencies": {"typescript": "^5.0.0", "posthog-js": "^1.0.0"}}')
            install_result = subprocess.run(
                ["pnpm", "install", "--no-frozen-lockfile"],
                cwd=str(tmpdir_path),
                capture_output=True,
                text=True,
                timeout=120,
            )

            if install_result.returncode != 0:
                self.fail(
                    f"Failed to install dependencies:\n"
                    f"STDOUT: {install_result.stdout}\n"
                    f"STDERR: {install_result.stderr}"
                )

            # Write generated types (using real posthog-js)
            types_file = tmpdir_path / "posthog-typed.ts"
            types_file.write_text(ts_content)

            # Create test file that exercises all type scenarios
            test_file = tmpdir_path / "test.ts"
            test_file.write_text(
                """
import posthog, { EventName } from './posthog-typed'

// ========================================
// TEST 1: Additional properties are allowed
// ========================================

// ✅ Should compile: required field + extra properties (CRITICAL TEST)
posthog.capture('test_event', {
    required_field: 123,
    optional_field: 'test',
    extra_property: 'this should be allowed',
    another_extra: true,
    nested_extra: { foo: 'bar' }
})

// ✅ Should compile: only required field
posthog.capture('test_event', {
    required_field: 456
})

// ========================================
// TEST 2: Required properties are validated
// ========================================

// ❌ Should fail: missing required field
// @ts-expect-error
posthog.capture('test_event', {
    optional_field: 'test'
})

// ❌ Should fail: wrong type for required field
// @ts-expect-error
posthog.capture('test_event', {
    required_field: 'string not allowed'
})

// ========================================
// TEST 3: Events with all optional properties
// ========================================

// ✅ Should compile: no properties needed
posthog.capture('optional_event')

// ✅ Should compile: with properties
posthog.capture('optional_event', {
    optional_only: 'value',
    extra_field: 123
})

// ========================================
// TEST 4: Untyped events accept anything
// ========================================

// ✅ Should compile: any properties
posthog.capture('untyped_event', {
    anything: 'goes',
    here: 123
})

// ✅ Should compile: no properties
posthog.capture('untyped_event')

// ========================================
// TEST 5: Undefined events work flexibly
// ========================================

// ✅ Should compile: custom event with properties
posthog.capture('custom_undefined_event', {
    any: 'properties',
    work: 'here'
})

// ✅ Should compile: custom event without properties
posthog.capture('another_custom_event')

// ========================================
// TEST 6: String variables are blocked
// ========================================

// ❌ Should fail: broad string type not allowed
let stringVar: string = 'test_event'
// @ts-expect-error
posthog.capture(stringVar)

// ✅ Should compile: EventName type works
let typedVar: EventName = 'test_event'
posthog.capture(typedVar, { required_field: 789 })

// ✅ Should compile: const infers literal type
const constVar = 'test_event'
posthog.capture(constVar, { required_field: 999 })

// ========================================
// TEST 7: captureRaw bypasses all checking
// ========================================

// ✅ Should compile: missing required fields is OK
posthog.captureRaw('test_event', {
    optional_field: 'test'
})

// ✅ Should compile: wrong types are OK
posthog.captureRaw('test_event', {
    required_field: 'string is fine here'
})

// ✅ Should compile: string variables work
posthog.captureRaw(stringVar, { any: 'data' })

// ========================================
// TEST 8: Special characters are escaped
// ========================================

// ✅ Should compile: event and property names with special chars
posthog.capture("a'a\\\\'b\\"c>?>%}}%%>c<[[?${{%}}cake'", {
    "prop'with\\\\'quotes\\"\\\\slash": 'value'
})
"""
            )

            # Create tsconfig.json
            tsconfig_file = tmpdir_path / "tsconfig.json"
            tsconfig_file.write_text(
                """
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "lib": ["ES2020", "DOM"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "moduleResolution": "node"
  }
}
"""
            )

            # Run TypeScript compiler using pnpm
            result = subprocess.run(
                ["pnpm", "exec", "tsc", "--noEmit", "--project", str(tsconfig_file)],
                cwd=str(tmpdir_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Assert compilation succeeded
            self.assertEqual(
                result.returncode,
                0,
                f"TypeScript compilation failed. This indicates the type system is broken.\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}\n\n"
                f"Generated TypeScript file location: {types_file}",
            )
