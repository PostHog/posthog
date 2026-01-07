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
            ("snake_case", "downloaded_file", "capture_downloaded_file"),
            ("kebab_case", "user-signed-up", "capture_user_signed_up"),
            ("dollar_prefix", "$pageview", "capture_pageview"),
            ("mixed_case", "API-Request", "capture_api_request"),
            ("with_numbers", "test_123", "capture_test_123"),
            ("multiple_underscores", "___test___", "capture_test"),
            ("empty_string", "", "capture_event"),
            ("starts_with_number", "123_start", "capture_event_123_start"),
            ("only_numbers", "123456", "capture_event_123456"),
            ("spaces", "dashboard mode toggled", "capture_dashboard_mode_toggled"),
        ]
    )
    def test_to_method_name(self, name, event_name, expected_output):
        result = self.generator._to_method_name(event_name)
        assert expected_output == result, f"{name} failed: Expected '{event_name}' to convert to '{expected_output}', got '{result}'"

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
        result = self.generator._to_python_identifier(input_name)
        assert expected_output == result, f"{name} failed: Expected '{input_name}' to convert to '{expected_output}', got '{result}'"

    def test_get_unique_name_collision_handling(self):
        used_names: set[str] = set()

        name1 = self.generator._get_unique_name("file_name", used_names)
        assert name1 == "file_name"
        assert "file_name" in used_names

        name2 = self.generator._get_unique_name("file_name", used_names)
        assert name2 == "file_name_2"
        assert "file_name_2" in used_names

        name3 = self.generator._get_unique_name("file_name", used_names)
        assert name3 == "file_name_3"

    def test_generate_capture_method_without_properties(self):
        method = self.generator._generate_capture_method("simple_event", [], set())

        assert method.strip() == '''def capture_simple_event(\n        self,\n        *,\n        extra_properties: Optional[Dict[str, Any]] = None,\n        **kwargs: Unpack[OptionalCaptureArgs],\n    ) -> Optional[str]:\n        """Capture a `simple_event` event."""\n        return self.capture("simple_event", properties=extra_properties, **kwargs)'''

    def test_generate_capture_method_with_only_optional(self):
        method = self.generator._generate_capture_method(
            "file_downloaded",
            [
                self._create_mock_property("label", "String", required=False),
                self._create_mock_property("value", "Numeric", required=False),
            ],
            set(),
        )

        assert method.strip() == '''def capture_file_downloaded(\n        self,\n        *,\n        # Optional event properties\n        label: Optional[str] = None,\n        value: Optional[float] = None,\n        # Additional untyped properties\n        extra_properties: Optional[Dict[str, Any]] = None,\n        # SDK kwargs (distinct_id, timestamp, etc.)\n        **kwargs: Unpack[OptionalCaptureArgs],\n    ) -> Optional[str]:\n        """Capture a `file_downloaded` event with type-safe properties."""\n        properties: Dict[str, Any] = {}\n        if label is not None:\n            properties["label"] = label\n        if value is not None:\n            properties["value"] = value\n        if extra_properties is not None:\n            properties.update(extra_properties)\n        return self.capture("file_downloaded", properties=properties, **kwargs)'''

    def test_generate_capture_method_with_method_name_clash(self):
        used_method_names: set[str] = set()
        method_one = self.generator._generate_capture_method(
            "file_downloaded",
            [],
            used_method_names,
        )
        method_two = self.generator._generate_capture_method("file-downloaded", [], used_method_names)

        assert method_one.strip() == '''def capture_file_downloaded(\n        self,\n        *,\n        extra_properties: Optional[Dict[str, Any]] = None,\n        **kwargs: Unpack[OptionalCaptureArgs],\n    ) -> Optional[str]:\n        """Capture a `file_downloaded` event."""\n        return self.capture("file_downloaded", properties=extra_properties, **kwargs)'''
        assert method_two.strip() == '''def capture_file_downloaded_2(\n        self,\n        *,\n        extra_properties: Optional[Dict[str, Any]] = None,\n        **kwargs: Unpack[OptionalCaptureArgs],\n    ) -> Optional[str]:\n        """Capture a `file-downloaded` event."""\n        return self.capture("file-downloaded", properties=extra_properties, **kwargs)'''

    def test_generate_capture_method_with_mixed_properties(self):
        method = self.generator._generate_capture_method(
            "file_downloaded",
            [
                self._create_mock_property("file_name", "String", required=True),
                self._create_mock_property("file_size", "Numeric", required=True),
                self._create_mock_property("file-size", "Array", required=True),  # Collision
                self._create_mock_property("file_extension", "String", required=False),
                self._create_mock_property("label", "String", required=False),
                self._create_mock_property("value", "Numeric", required=False),
                self._create_mock_property('foo"bar', "String", required=True),
                self._create_mock_property("class", "String", required=False),
            ],
            set(),
        )

        assert method.strip() == '''def capture_file_downloaded(\n        self,\n        *,\n        # Required event properties\n        file_size: List[Any],\n        file_name: str,\n        file_size_2: float,\n        foo_bar: str,\n        # Optional event properties\n        class_: Optional[str] = None,\n        file_extension: Optional[str] = None,\n        label: Optional[str] = None,\n        value: Optional[float] = None,\n        # Additional untyped properties\n        extra_properties: Optional[Dict[str, Any]] = None,\n        # SDK kwargs (distinct_id, timestamp, etc.)\n        **kwargs: Unpack[OptionalCaptureArgs],\n    ) -> Optional[str]:\n        """Capture a `file_downloaded` event with type-safe properties."""\n        properties: Dict[str, Any] = {"file-size": file_size, "file_name": file_name, "file_size": file_size_2, "foo\\"bar": foo_bar}\n        if class_ is not None:\n            properties["class"] = class_\n        if file_extension is not None:\n            properties["file_extension"] = file_extension\n        if label is not None:\n            properties["label"] = label\n        if value is not None:\n            properties["value"] = value\n        if extra_properties is not None:\n            properties.update(extra_properties)\n        return self.capture("file_downloaded", properties=properties, **kwargs)'''

    def test_full_generation_empty_output(self):
        code = self.generator.generate([], {})  # type: ignore[arg-type]

        assert "GENERATED FILE - DO NOT EDIT" in code
        assert "from datetime import datetime" not in code
        assert '''class PosthogTyped(Posthog):\n    """\n    A type-safe PostHog client with per-event capture methods.\n\n    Drop-in replacement for Posthog that provides IDE autocomplete\n    and type checking via capture_<event_name>() methods.\n    """\n\n    pass''' in code

    def test_full_generation_output(self):
        event = MagicMock()
        event.id = "1"
        event.name = 'simple_"event'
        schema_map = {
            "1": [
                self._create_mock_property("user_id", "String", required=True),
                self._create_mock_property("c'ount", "Numeric", required=False),
                self._create_mock_property("file-name", "String", required=True),
                self._create_mock_property("file_name", "Object", required=True),
                self._create_mock_property("created_at", "DateTime", required=False),
                self._create_mock_property("optional_items", "Array", required=False),
            ],
        }

        code = self.generator.generate([event], schema_map)  # type: ignore[arg-type]

        assert "GENERATED FILE - DO NOT EDIT" in code
        assert "from datetime import datetime" in code
        assert "class PosthogTyped(Posthog):" in code

        assert '''def capture_simple_event(\n        self,\n        *,\n        # Required event properties\n        file_name: str,\n        file_name_2: Dict[str, Any],\n        user_id: str,\n        # Optional event properties\n        c_ount: Optional[float] = None,\n        created_at: Optional[datetime] = None,\n        optional_items: Optional[List[Any]] = None,\n        # Additional untyped properties\n        extra_properties: Optional[Dict[str, Any]] = None,\n        # SDK kwargs (distinct_id, timestamp, etc.)\n        **kwargs: Unpack[OptionalCaptureArgs],\n    ) -> Optional[str]:\n        """Capture a `simple_\\"event` event with type-safe properties."""\n        properties: Dict[str, Any] = {"file-name": file_name, "file_name": file_name_2, "user_id": user_id}\n        if c_ount is not None:\n            properties["c\'ount"] = c_ount\n        if created_at is not None:\n            properties["created_at"] = created_at\n        if optional_items is not None:\n            properties["optional_items"] = optional_items\n        if extra_properties is not None:\n            properties.update(extra_properties)\n        return self.capture("simple_\\"event", properties=properties, **kwargs)''' in code

    def _create_mock_property(self, name: str, property_type: str, required: bool = False) -> MagicMock:
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
        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        assert "content" in data
        assert "event_count" in data
        assert "schema_hash" in data
        assert "generator_version" in data

        code = data["content"]
        assert "from posthog import Posthog" in code
        assert "class PosthogTyped(Posthog):" in code
        assert "def capture_file_downloaded(" in code
        assert "def capture_user_signed_up(" in code

        self._test_telemetry_called(mock_report)

    def test_python_endpoint_excludes_non_whitelisted_system_events(self):
        EventDefinition.objects.create(team=self.team, project=self.project, name="$autocapture")
        EventDefinition.objects.create(team=self.team, project=self.project, name="$pageview")

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")

        code = response.json()["content"]
        assert "capture_autocapture" not in code
        assert "capture_pageview" in code

    @patch("posthog.api.event_definition_generators.base.report_user_action")
    def test_python_endpoint_handles_no_events(self, mock_report):
        EventDefinition.objects.filter(team=self.team).delete()

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["event_count"] == 0
        assert "from posthog import Posthog" in data["content"]
        assert "class PosthogTyped(Posthog):" in data["content"]

        self._test_telemetry_called(mock_report)

    def test_python_schema_hash_is_deterministic(self):
        response1 = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
        hash1 = response1.json()["schema_hash"]

        response2 = self.client.get(f"/api/projects/{self.project.id}/event_definitions/python")
        hash2 = response2.json()["schema_hash"]

        assert hash1 == hash2, "Schema hash should be deterministic"

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
            assert response.status_code == status.HTTP_200_OK
            python_content = response.json()["content"]

            # Write generated types
            types_file = tmpdir_path / "posthog_typed.py"
            types_file.write_text(python_content)

            # Create pyproject.toml for mypy config
            pyproject_file = tmpdir_path / "pyproject.toml"
            # If we upgrade the minimum version, to Python >=3.11 we can also get rid of the `from typing_extensions`
            # import as those types are fully supported by then.
            pyproject_file.write_text(
                """
[tool.mypy]
python_version = "3.9"
strict = false
"""
            )

            # Create a virtual environment and install the posthog SDK
            # This ensures mypy can find the real SDK
            import sys

            venv_path = tmpdir_path / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True, capture_output=True)
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

            # Define test cases: name -> (code, should_pass, expected_error_text)
            test_cases = {
                "full_event_with_all_properties": (
                    """
client = PosthogTyped("fake_key", host="http://localhost")
client.capture_file_downloaded(
    file_name="document.pdf",
    file_size=1024.0,
    downloaded_at=datetime.now(),
    file_extension="pdf",
    distinct_id="user_123",
)
""",
                    True,
                    None,
                ),
                "event_with_only_required_properties": (
                    """
client = PosthogTyped("fake_key", host="http://localhost")
client.capture_user_signed_up(
    email="user@example.com",
    plan="free",
    distinct_id="user_456",
)
""",
                    True,
                    None,
                ),
                "distinct_id_is_optional": (
                    """
client = PosthogTyped("fake_key", host="http://localhost")
client.capture_file_downloaded(
    file_name="document.pdf",
    file_size=1024.0,
    downloaded_at=datetime.now(),
)
""",
                    True,
                    None,
                ),
                "missing_required_property_file_size": (
                    """
client = PosthogTyped("fake_key", host="http://localhost")
client.capture_file_downloaded(
    file_name="document.pdf",
    downloaded_at=datetime.now(),
    distinct_id="user_123",
)
""",
                    False,
                    'Missing named argument "file_size"',
                ),
                "wrong_type_string_instead_of_float": (
                    """
client = PosthogTyped("fake_key", host="http://localhost")
client.capture_file_downloaded(
    file_name="document.pdf",
    file_size="not a number",
    downloaded_at=datetime.now(),
    distinct_id="user_123",
)
""",
                    False,
                    'Argument "file_size" to "capture_file_downloaded"',
                ),
                "extra_properties_allowed": (
                    """
client = PosthogTyped("fake_key", host="http://localhost")
client.capture_file_downloaded(
    file_name="document.pdf",
    file_size=1024.0,
    downloaded_at=datetime.now(),
    extra_properties={"custom_field": "custom_value", "another": 123},
    distinct_id="user_123",
)
""",
                    True,
                    None,
                ),
            }

            test_file = tmpdir_path / "test_usage.py"
            failures = []

            for name, (code, should_pass, expected_error) in test_cases.items():
                test_content = f"""from datetime import datetime
from posthog_typed import PosthogTyped
{code}"""
                test_file.write_text(test_content)

                result = subprocess.run(
                    [str(venv_python), "-m", "mypy", str(test_file), "--config-file", str(pyproject_file)],
                    cwd=str(tmpdir_path),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if should_pass and result.returncode != 0:
                    failures.append(f"{name}: expected to pass but failed:\n{result.stdout}")
                elif not should_pass and result.returncode == 0:
                    failures.append(f"{name}: expected to fail but passed")
                elif not should_pass and (expected_error and expected_error not in result.stdout):
                    failures.append(f"{name}: expected '{expected_error}' in error output, got:\n{result.stdout}")

            if failures:
                self.fail(
                    "Type checking failures:\n\n"
                    + "\n\n".join(failures)
                    + f"\n\nGenerated Python file:\n{python_content}"
                )

    def _test_telemetry_called(self, mock_report) -> None:
        assert mock_report.call_count == 1
        call_args = mock_report.call_args
        assert call_args[0][0] == self.user
        assert call_args[0][1] == "event definitions generated"
        telemetry_props = call_args[0][2]
        assert telemetry_props["language"] == "Python"
        assert telemetry_props["team_id"] == self.team.id
        assert telemetry_props["project_id"] == self.project.id
