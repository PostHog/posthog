import tempfile
import subprocess
from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.event_definition_generators.python import PythonGenerator
from posthog.models import EventDefinition, EventSchema, SchemaPropertyGroup, SchemaPropertyGroupProperty


class TestPythonGenerator(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.generator = PythonGenerator()

    @parameterized.expand(
        [
            ("snake_case", "downloaded_file", "DownloadedFileProps"),
            ("kebab_case", "user-signed-up", "UserSignedUpProps"),
            ("dollar_prefix", "$pageview", "PageviewProps"),
            ("mixed_case", "API-Request", "ApiRequestProps"),
            ("with_numbers", "test_123", "Test123Props"),
            ("multiple_underscores", "___test___", "TestProps"),
            ("empty_string", "", "EventProps"),
            ("starts_with_number", "123_start", "Event123StartProps"),
            ("only_numbers", "123456", "Event123456Props"),
        ]
    )
    def test_to_class_name(self, name, event_name, expected_output):
        result = self.generator._to_class_name(event_name)
        self.assertEqual(
            expected_output,
            result,
            f"{name} failed: Expected '{event_name}' to convert to '{expected_output}', got '{result}'",
        )

    @parameterized.expand(
        [
            ("snake_case", "file_name", "file_name"),
            ("kebab_case", "user-id", "user_id"),
            ("with_numbers", "test_123", "test_123"),
            ("empty", "", "value"),
            ("whitespace_only", "   ", "value"),
            ("reserved_keyword_class", "class", "class_"),
            ("reserved_keyword_def", "def", "def_"),
            ("reserved_keyword_import", "import", "import_"),
            ("multiple_parts", "multi part argument", "multi_part_argument"),
            ("trailing_underscore", "name_", "name"),
            ("mixed_separators", "user-id_name", "user_id_name"),
            ("leading_underscore", "_private", "private"),
            ("starts_with_number", "123test", "prop_123test"),
            ("special_chars", "$name@#$value", "name_value"),
            ("only_special_chars", "@#$%", "value"),
        ]
    )
    def test_to_python_identifier(self, name, input_name, expected_output):
        """Test property name to Python identifier conversion"""
        result = self.generator._to_python_identifier(input_name)
        self.assertEqual(
            expected_output,
            result,
            f"{name} failed: Expected '{input_name}' to convert to '{expected_output}', got '{result}'",
        )

    def test_get_unique_name_collision_handling(self):
        used_names: set[str] = set()

        # First usage - no collision
        name1 = self.generator._get_unique_name("file_name", used_names)
        self.assertEqual(name1, "file_name")
        self.assertIn("file_name", used_names)

        # Second usage of same base - should get suffix
        name2 = self.generator._get_unique_name("file_name", used_names)
        self.assertEqual(name2, "file_name_2")
        self.assertIn("file_name_2", used_names)

        # Third usage
        name3 = self.generator._get_unique_name("file_name", used_names)
        self.assertEqual(name3, "file_name_3")

    def test_generate_typed_dict_without_properties(self):
        result, mappings = self.generator._generate_typed_dict("123_simple", [])

        self.assertEqual(
            result.strip(),
            '''class Event123SimpleProps(TypedDict, total=False):
    """Properties for the `123_simple` event (no schema defined)"""
    pass''',
        )
        self.assertEqual(mappings, {})

    def test_generate_typed_dict_with_properties(self):
        result, mappings = self.generator._generate_typed_dict(
            "file_uploaded",
            [
                self._create_mock_property('file_"name', "DateTime", required=True),
                self._create_mock_property("file_name", "String", required=True),  # Collides after conversion
                self._create_mock_property("file_size", "Numeric", required=True),
                self._create_mock_property("is-active", "Boolean", required=False),
                self._create_mock_property("object", "Object", required=False),
                self._create_mock_property("class", "String", required=True),  # reserved keyword
            ],
        )

        self.assertEqual(
            result.strip(),
            '''class FileUploadedProps(TypedDict, total=False):
    """Properties for the `file_uploaded` event"""
    class_: Required[str]
    file_name: Required[datetime]
    file_name_2: Required[str]
    file_size: Required[float]
    is_active: NotRequired[bool]
    object: NotRequired[Dict[str, Any]]''',
        )
        self.assertEqual(
            mappings,
            {"class_": "class", "file_name": 'file_"name', "file_name_2": "file_name", "is_active": "is-active"},
        )

    def test_generate_overload_with_no_required_properties(self):
        overload = self.generator._generate_overload(
            "no_required_properties",
            [
                self._create_mock_property("is-active", "Boolean", required=False),
                self._create_mock_property("object", "Object", required=False),
            ],
        )

        self.assertEqual(
            overload.strip(),
            """@overload
def capture(  # type: ignore[misc]  # This is needed to ensure our typed `properties` take precedence over the SDK kwargs
    event: Literal["no_required_properties"],
    *,
    properties: Optional[NoRequiredPropertiesProps] = ...,
    **kwargs: Unpack[OptionalCaptureArgs],
) -> Optional[str]: ...""",
        )

    def test_generate_overload_with_required_properties(self):
        overload = self.generator._generate_overload(
            "with_required_properties",
            [
                self._create_mock_property("file_name", "String", required=True),
                self._create_mock_property("file_size", "Numeric", required=True),
                self._create_mock_property("is-active", "Boolean", required=False),
                self._create_mock_property("object", "Object", required=False),
            ],
        )

        self.assertEqual(
            overload.strip(),
            """@overload
def capture(  # type: ignore[misc]  # This is needed to ensure our typed `properties` take precedence over the SDK kwargs
    event: Literal["with_required_properties"],
    *,
    properties: WithRequiredPropertiesProps,
    **kwargs: Unpack[OptionalCaptureArgs],
) -> Optional[str]: ...""",
        )

    def test_full_generation_empty_output(self):
        """
        This test 'globally' checks the output of the `generate` function when no data is passed.
        """
        code = self.generator.generate([], {})  # type: ignore[arg-type]

        # Check header
        self.assertIn("GENERATED FILE - DO NOT EDIT", code)
        self.assertIn("auto-generated by PostHog", code)
        self.assertNotIn("from datetime import datetime", code)

        # Check key components in the body
        self.assertIn("""_PROPERTY_MAPPINGS: Dict[str, Dict[str, str]] = {}""", code)

    def test_full_generation_output(self):
        """
        This test 'globally' checks the output of the `generate` function.
        This is only done globally as the 'critical' parts have already been covered in other tests here.
        """
        event = MagicMock()
        event.id = "1"
        event.name = 'simple_"event'
        schema_map = {
            "1": [
                self._create_mock_property("user_id", "String", required=True),
                self._create_mock_property("c'ount", "Numeric", required=False),
                self._create_mock_property("file-name", "String", required=True),
                self._create_mock_property("file_name", "Object", required=True),  # Collision
                self._create_mock_property("created_at", "DateTime", required=False),
            ]
        }

        code = self.generator.generate([event], schema_map)  # type: ignore[arg-type]

        # Check header
        self.assertIn("GENERATED FILE - DO NOT EDIT", code)
        self.assertIn("auto-generated by PostHog", code)
        self.assertIn("from datetime import datetime", code)

        # Check key components in the body
        self.assertIn(
            """# Property name mappings (EventName => Python identifier -> original property name)
_PROPERTY_MAPPINGS: Dict[str, Dict[str, str]] = {
    "simple_\\"event": {
        "c_ount": "c'ount",
        "file_name": "file-name",
        "file_name_2": "file_name",
    },
}""",
            code,
        )
        self.assertIn(
            '''class SimpleEventProps(TypedDict, total=False):
    """Properties for the `simple_\\"event` event"""
    file_name: Required[str]
    file_name_2: Required[Dict[str, Any]]
    user_id: Required[str]
    c_ount: NotRequired[float]
    created_at: NotRequired[datetime]''',
            code,
        )
        self.assertIn(
            """# Type-safe capture overloads
@overload
def capture(  # type: ignore[misc]  # This is needed to ensure our typed `properties` take precedence over the SDK kwargs
    event: Literal["simple_\\"event"],
    *,
    properties: SimpleEventProps,
    **kwargs: Unpack[OptionalCaptureArgs],
) -> Optional[str]: ...""",
            code,
        )

    def _create_mock_property(self, name: str, property_type: str, required: bool = False) -> MagicMock:
        """Create a mock SchemaPropertyGroupProperty for testing"""
        prop = MagicMock()
        prop.name = name
        prop.property_type = property_type
        prop.is_required = required
        return prop


class TestPythonGeneratorAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.event_def_1 = EventDefinition.objects.create(team=self.team, project=self.project, name="file_downloaded")
        self.prop_group_1 = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="File Download Properties"
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_1,
            name="file_name",
            property_type="String",
            is_required=True,
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_1,
            name="file_size",
            property_type="Numeric",
            is_required=True,
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_1,
            name="downloaded_at",
            property_type="DateTime",
            is_required=True,
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_1,
            name="file_extension",
            property_type="String",
            is_required=False,
        )
        EventSchema.objects.create(event_definition=self.event_def_1, property_group=self.prop_group_1)

        self.event_def_2 = EventDefinition.objects.create(team=self.team, project=self.project, name="user_signed_up")
        self.prop_group_2 = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="User Signup Properties"
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_2,
            name="email",
            property_type="String",
            is_required=True,
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_2,
            name="plan",
            property_type="String",
            is_required=True,
        )
        EventSchema.objects.create(event_definition=self.event_def_2, property_group=self.prop_group_2)

    @patch("posthog.api.event_definition_generators.base.report_user_action")
    def test_python_endpoint_success(self, mock_report):
        """Test that the python endpoint returns valid code"""
        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        # Check response structure
        self.assertIn("content", data)
        self.assertIn("event_count", data)
        self.assertIn("schema_hash", data)
        self.assertIn("generator_version", data)

        # Check code content
        code = data["content"]
        self.assertIn("import posthog", code)
        self.assertIn("class FileDownloadedProps", code)
        self.assertIn("class UserSignedUpProps", code)

        # Verify telemetry was called
        self._test_telemetry_called(mock_report)

    def test_python_endpoint_excludes_non_whitelisted_system_events(self):
        # $autocapture should be excluded
        # $pageview is whitelisted and should be included
        EventDefinition.objects.create(team=self.team, project=self.project, name="$autocapture")
        EventDefinition.objects.create(team=self.team, project=self.project, name="$pageview")

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")

        code = response.json()["content"]
        self.assertNotIn("Autocapture", code)
        self.assertIn("Pageview", code)

    @patch("posthog.api.event_definition_generators.base.report_user_action")
    def test_python_endpoint_handles_no_events(self, mock_report):
        """Test endpoint behavior when no events exist"""
        EventDefinition.objects.filter(team=self.team).delete()

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["event_count"], 0)
        self.assertIn("import posthog", data["content"])

        self._test_telemetry_called(mock_report)

    def test_python_schema_hash_is_deterministic(self):
        """Test that schema_hash is deterministic for the same schema"""
        response1 = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
        hash1 = response1.json()["schema_hash"]

        response2 = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
        hash2 = response2.json()["schema_hash"]

        self.assertEqual(hash1, hash2, "Schema hash should be deterministic")

    def test_python_code_type_checks(self):
        """
        Integration test that verifies the generated Python code passes type checking.

        This test:
        1. Creates event definitions with schemas
        2. Generates Python code via the API endpoint
        3. Creates a test file that uses the types
        4. Runs mypy to verify type correctness
        """
        special_event = EventDefinition.objects.create(
            team=self.team, project=self.project, name="user'event\"with\\quotes"
        )
        special_group = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="Special Properties"
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=special_group,
            name="prop'with\"quotes",
            property_type="String",
            is_required=True,
        )
        EventSchema.objects.create(event_definition=special_event, property_group=special_group)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            python_content = response.json()["content"]

            # Write generated types
            types_file = tmpdir_path / "posthog_typed.py"
            types_file.write_text(python_content)

            # Create test file that uses the generated code
            test_file = tmpdir_path / "test_usage.py"
            test_file.write_text(
                """
from datetime import datetime

# Import typed module for type-safe captures
import posthog_typed
from posthog_typed import FileDownloadedProps, UserSignedUpProps

# Import regular posthog for untyped/dynamic events
import posthog

# Test 1: Using posthog_typed.capture (type-checked)
posthog_typed.capture(
    "file_downloaded",
    distinct_id="user_123",
    properties={
        "file_name": "document.pdf",
        "file_size": 1024.0,
        "downloaded_at": datetime.now(),  # required
        "file_extension": "pdf",  # optional
    },
)

# Test 2: Event with only required properties
posthog_typed.capture(
    "user_signed_up",
    distinct_id="user_456",
    properties={"email": "user@example.com", "plan": "free"},
)

# Test 3: posthog.capture for dynamic events (no type checking)
posthog.capture(
    "any_event",
    distinct_id="user_789",
    properties={"anything": "goes"},
)

# Test 4: Using TypedDict directly
props: FileDownloadedProps = {
    "file_name": "test.txt",
    "file_size": 100.0,
    "downloaded_at": datetime.now(),
}
posthog_typed.capture("file_downloaded", distinct_id="user_999", properties=props)
"""
            )

            # Create pyproject.toml for mypy config
            pyproject_file = tmpdir_path / "pyproject.toml"
            pyproject_file.write_text(
                """
[tool.mypy]
python_version = "3.11"
strict = false
"""
            )

            # Create a virtual environment and install the posthog SDK
            # This ensures mypy can find the real SDK, not the local posthog directory
            import sys

            venv_path = tmpdir_path / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True, capture_output=True)

            # Determine the pip and python paths in the venv
            if sys.platform == "win32":
                venv_pip = venv_path / "Scripts" / "pip"
                venv_python = venv_path / "Scripts" / "python"
            else:
                venv_pip = venv_path / "bin" / "pip"
                venv_python = venv_path / "bin" / "python"

            # Install posthog SDK and mypy in the venv
            install_result = subprocess.run(
                [str(venv_pip), "install", "posthog", "mypy"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if install_result.returncode != 0:
                self.fail(
                    f"Failed to install posthog SDK:\n"
                    f"STDOUT: {install_result.stdout}\n"
                    f"STDERR: {install_result.stderr}"
                )

            # Run mypy type checker using the venv's mypy
            result = subprocess.run(
                [
                    str(venv_python),
                    "-m",
                    "mypy",
                    str(test_file),
                    "--config-file",
                    str(pyproject_file),
                ],
                cwd=str(tmpdir_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Assert type checking passed
            self.assertEqual(
                result.returncode,
                0,
                f"mypy type checking failed. This indicates the generated code has type errors.\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}\n\n"
                f"Generated Python file:\n{python_content}",
            )

    def _test_telemetry_called(self, mock_report) -> None:
        """Verify telemetry was called correctly"""
        self.assertEqual(mock_report.call_count, 1)
        call_args = mock_report.call_args
        self.assertEqual(call_args[0][0], self.user)
        self.assertEqual(call_args[0][1], "event definitions generated")
        telemetry_props = call_args[0][2]
        self.assertEqual(telemetry_props["language"], "Python")
        self.assertEqual(telemetry_props["team_id"], self.team.id)
        self.assertEqual(telemetry_props["project_id"], self.project.id)
