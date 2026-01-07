import re
import tempfile
import subprocess
from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.event_definition_generators.golang import GolangGenerator
from posthog.models import EventDefinition, EventSchema, SchemaPropertyGroup, SchemaPropertyGroupProperty


class TestGolangGenerator(APIBaseTest):
    """Test the GolangGenerator class directly"""

    def setUp(self):
        super().setUp()
        self.generator = GolangGenerator()

    @parameterized.expand(
        [
            ("snake_case", "downloaded_file", "DownloadedFile"),
            ("kebab_case", "user-signed-up", "UserSignedUp"),
            ("dollar_prefix", "$pageview", "Pageview"),
            ("mixed_case", "API-Request", "APIRequest"),
            ("with_numbers", "test_123", "Test123"),
            ("multiple_underscores", "___test___", "Test"),
            ("empty_string", "", "Event"),
            ("starts_with_number", "123_start", "Event123Start"),
            ("only_numbers", "123456", "Event123456"),
        ]
    )
    def test_to_go_func_name(self, name, event_name, expected_output):
        """Test event name to Go exported identifier conversion"""
        result = self.generator._to_go_func_name(event_name)
        assert expected_output == result, f"{name} failed: Expected '{event_name}' to convert to '{expected_output}', got '{result}'"

    @parameterized.expand(
        [
            ("snake_case", "file_name", "fileName"),
            ("kebab_case", "user-id", "userId"),
            ("underscore_with_abbrev", "api_key", "apiKey"),
            ("already_camelCase", "firstName", "firstname"),
            ("all_caps", "URL", "url"),
            ("with_numbers", "test_123", "test123"),
            ("empty", "", "value"),
            ("whitespace_only", "   ", "value"),
            ("reserved_keywords", "break", "break_"),
            ("reserved_mixed_case", "Func", "func_"),
            ("multiple_parts", "multi part argument", "multiPartArgument"),
            ("multi_part_with_reserved", "this will not break", "thisWillNotBreak"),
            ("trailing_underscore", "name_", "name"),
            ("mixed_separators", "user-id_name", "userIdName"),
            ("leading_underscore", "_private", "private"),
            ("starts_with_number", "123test", "param123test"),
            ("special_chars", "$name@#$value", "nameValue"),
            ("all_lowercase_no_sep", "filename", "filename"),
            ("consecutive_capitals", "HTTPResponse", "httpresponse"),
            ("only_special_chars", "@#$%", "value"),
        ]
    )
    def test_to_go_param_name(self, name, input_name, expected_output):
        """Test property name to Go parameter name conversion (camelCase)"""
        result = self.generator._to_go_param_name(input_name)
        assert expected_output == result, f"{name} failed: Expected '{input_name}' to convert to '{expected_output}', got '{result}'"

    @parameterized.expand(
        [
            ("snake_case", "file_name", "FileName"),
            ("with_numbers", "test_123", "Test123"),
            ("empty", "", "Prop"),
            ("whitespace_only", "   ", "Prop"),
            ("mixed_separators", "user-id_name", "UserIdName"),
            ("leading_underscore", "_private", "Private"),
            ("starts_with_number", "123test", "123test"),
            ("special_chars", "$name@#$value", "NameValue"),
            ("consecutive_capitals", "HTTPResponse", "HTTPResponse"),
            ("only_special_chars", "@#$%", "Prop"),
        ]
    )
    def test_go_pascal_name_conversion(self, name, input_name, expected_output):
        result = self.generator._to_pascal_name(input_name)
        assert expected_output == result, f"{name} failed: Expected '{input_name}' to convert to '{expected_output}', got '{result}'"

    def test_get_unique_name(self):
        """Test collision handling in parameter name generation"""
        used_names: set[str] = set()

        # First usage - no collision
        name1 = self.generator._get_unique_name("fileName", used_names)
        assert name1 == "fileName"
        assert "fileName" in used_names

        # Second usage of same base - should get suffix
        name2 = self.generator._get_unique_name("fileName", used_names)
        assert name2 == "fileName2"
        assert "fileName2" in used_names

        # Third usage
        name3 = self.generator._get_unique_name("fileName", used_names)
        assert name3 == "fileName3"

    def test_generate_event_without_properties(self):
        """Test code generation for event without properties"""
        code = self.generator._generate_event_without_properties("simple_click")
        assert '''// SimpleClickCapture creates a capture for the "simple_click" event.\n// This event has no defined schema properties.\nfunc SimpleClickCapture(distinctId string, properties ...posthog.Properties) posthog.Capture {\n\tprops := posthog.Properties{}\n\tfor _, p := range properties {\n\t\tfor k, v := range p {\n\t\t\tprops[k] = v\n\t\t}\n\t}\n\n\treturn posthog.Capture{\n\t\tDistinctId: distinctId,\n\t\tEvent:      "simple_click",\n\t\tProperties: props,\n\t}\n}\n\n// SimpleClickCaptureFromBase creates a posthog.Capture for the "simple_click" event\n// starting from an existing base capture. The event name is overridden, and\n// any additional properties can be passed via the properties parameter.\nfunc SimpleClickCaptureFromBase(base posthog.Capture, properties ...posthog.Properties) posthog.Capture {\n\tprops := posthog.Properties{}\n\tfor _, p := range properties {\n\t\tfor k, v := range p {\n\t\t\tprops[k] = v\n\t\t}\n\t}\n\n\tbase.Event = "simple_click"\n\tif base.Properties == nil {\n\t\tbase.Properties = posthog.Properties{}\n\t}\n\tbase.Properties = base.Properties.Merge(props)\n\n\treturn base\n}''' == code.strip()

    def test_generate_event_with_properties(self):
        props = [
            self._create_mock_property("file_name", "String", required=True),
            self._create_mock_property("file_size", "Numeric", required=True),
            self._create_mock_property("is_active", "Boolean", required=False),
            self._create_mock_property("created_at", "DateTime", required=True),
            self._create_mock_property("tags", "Array", required=False),
            self._create_mock_property("metadata", "Object", required=False),
        ]

        code = self.generator._generate_event_with_properties("file_uploaded", props)  # type: ignore[arg-type]
        assert '''// FileUploadedOption configures optional properties for a "file_uploaded" capture.\ntype FileUploadedOption func(*posthog.Capture)\n\n// FileUploadedWithIsActive sets the "is_active" property on a "file_uploaded" event.\nfunc FileUploadedWithIsActive(isActive bool) FileUploadedOption {\n\treturn func(c *posthog.Capture) {\n\t\tif c.Properties == nil {\n\t\t\tc.Properties = posthog.Properties{}\n\t\t}\n\t\tc.Properties["is_active"] = isActive\n\t}\n}\n\n// FileUploadedWithMetadata sets the "metadata" property on a "file_uploaded" event.\nfunc FileUploadedWithMetadata(metadata map[string]interface{}) FileUploadedOption {\n\treturn func(c *posthog.Capture) {\n\t\tif c.Properties == nil {\n\t\t\tc.Properties = posthog.Properties{}\n\t\t}\n\t\tc.Properties["metadata"] = metadata\n\t}\n}\n\n// FileUploadedWithTags sets the "tags" property on a "file_uploaded" event.\nfunc FileUploadedWithTags(tags []interface{}) FileUploadedOption {\n\treturn func(c *posthog.Capture) {\n\t\tif c.Properties == nil {\n\t\t\tc.Properties = posthog.Properties{}\n\t\t}\n\t\tc.Properties["tags"] = tags\n\t}\n}\n\n// FileUploadedWithExtraProps adds additional properties to a "file_uploaded" event.\nfunc FileUploadedWithExtraProps(props posthog.Properties) FileUploadedOption {\n\treturn func(c *posthog.Capture) {\n\t\tif c.Properties == nil {\n\t\t\tc.Properties = posthog.Properties{}\n\t\t}\n\t\tfor k, v := range props {\n\t\t\tc.Properties[k] = v\n\t\t}\n\t}\n}\n\n// FileUploadedCapture is a wrapper for the "file_uploaded" event.\n// It manages the creation of the `posthog.Capture`. If you need control over this, please make use of\n// the FileUploadedCaptureFromBase function.\n// Required properties from the schema are explicit parameters; optional properties\n// should be passed via FileUploadedWith* option functions.\nfunc FileUploadedCapture(\n\tdistinctId string,\n\tcreatedAt time.Time,\n\tfileName string,\n\tfileSize float64,\n\toptions ...FileUploadedOption,\n) posthog.Capture {\n\tprops := posthog.Properties{\n\t\t"created_at": createdAt,\n\t\t"file_name": fileName,\n\t\t"file_size": fileSize,\n\t}\n\n\tc := posthog.Capture{\n\t\tDistinctId: distinctId,\n\t\tEvent:      "file_uploaded",\n\t\tProperties: props,\n\t}\n\n\tfor _, opt := range options {\n\t\topt(&c)\n\t}\n\n\treturn c\n}\n\n// FileUploadedCaptureFromBase creates a posthog.Capture for the "file_uploaded" event\n// starting from an existing base capture. The event name is overridden, and\n// required properties from the schema are merged on top. Optional properties\n// should be passed via FileUploadedWith* option functions.\nfunc FileUploadedCaptureFromBase(\n\tbase posthog.Capture,\n\tcreatedAt time.Time,\n\tfileName string,\n\tfileSize float64,\n\toptions ...FileUploadedOption,\n) posthog.Capture {\n\tprops := posthog.Properties{\n\t\t"created_at": createdAt,\n\t\t"file_name": fileName,\n\t\t"file_size": fileSize,\n\t}\n\n\tbase.Event = "file_uploaded"\n\tif base.Properties == nil {\n\t\tbase.Properties = posthog.Properties{}\n\t}\n\tbase.Properties = base.Properties.Merge(props)\n\n\tfor _, opt := range options {\n\t\topt(&base)\n\t}\n\n\treturn base\n}''' == code.strip()

    def test_generate_event_with_quoted_and_escaped_properties(self):
        props = [
            self._create_mock_property("esc'ap\"eing", "String", required=True),
        ]

        code = self.generator._generate_event_with_properties("creative_naming", props)  # type: ignore[arg-type]
        assert """// CreativeNamingOption configures optional properties for a \"creative_naming\" capture.\ntype CreativeNamingOption func(*posthog.Capture)\n\n// CreativeNamingWithExtraProps adds additional properties to a \"creative_naming\" event.\nfunc CreativeNamingWithExtraProps(props posthog.Properties) CreativeNamingOption {\n\treturn func(c *posthog.Capture) {\n\t\tif c.Properties == nil {\n\t\t\tc.Properties = posthog.Properties{}\n\t\t}\n\t\tfor k, v := range props {\n\t\t\tc.Properties[k] = v\n\t\t}\n\t}\n}\n\n// CreativeNamingCapture is a wrapper for the \"creative_naming\" event.\n// It manages the creation of the `posthog.Capture`. If you need control over this, please make use of\n// the CreativeNamingCaptureFromBase function.\n// Required properties from the schema are explicit parameters; optional properties\n// should be passed via CreativeNamingWith* option functions.\nfunc CreativeNamingCapture(\n\tdistinctId string,\n\tescApEing string,\n\toptions ...CreativeNamingOption,\n) posthog.Capture {\n\tprops := posthog.Properties{\n\t\t\"esc'ap\\\"eing\": escApEing,\n\t}\n\n\tc := posthog.Capture{\n\t\tDistinctId: distinctId,\n\t\tEvent:      \"creative_naming\",\n\t\tProperties: props,\n\t}\n\n\tfor _, opt := range options {\n\t\topt(&c)\n\t}\n\n\treturn c\n}\n\n// CreativeNamingCaptureFromBase creates a posthog.Capture for the \"creative_naming\" event\n// starting from an existing base capture. The event name is overridden, and\n// required properties from the schema are merged on top. Optional properties\n// should be passed via CreativeNamingWith* option functions.\nfunc CreativeNamingCaptureFromBase(\n\tbase posthog.Capture,\n\tescApEing string,\n\toptions ...CreativeNamingOption,\n) posthog.Capture {\n\tprops := posthog.Properties{\n\t\t\"esc'ap\\\"eing\": escApEing,\n\t}\n\n\tbase.Event = \"creative_naming\"\n\tif base.Properties == nil {\n\t\tbase.Properties = posthog.Properties{}\n\t}\n\tbase.Properties = base.Properties.Merge(props)\n\n\tfor _, opt := range options {\n\t\topt(&base)\n\t}\n\n\treturn base\n}""" == code.strip()

    def test_full_generation_output(self):
        """
        This test 'globally' checks the output of the `generate` function.
        This is only done globally as the 'critical' parts have already been covered in other tests here.
        """
        event = MagicMock()
        event.id = "1"
        event.name = "simple_event"
        schema_map = {
            "1": [
                self._create_mock_property("user_id", "String", required=True),
                self._create_mock_property("count", "Numeric", required=False),
            ]
        }

        code = self.generator.generate([event], schema_map)  # type: ignore[arg-type]

        # Check header / imports
        assert "// Code generated by PostHog - DO NOT EDIT" in code
        assert "package typed" in code
        assert '"github.com/posthog/posthog-go"' in code
        assert '"time"' not in code, "time should not be imported as we do not have a DateTime property."

        # Check event code
        assert "SimpleEventOption" in code
        assert "SimpleEventWithCount" in code
        assert "SimpleEventWithExtraProps" in code
        assert "SimpleEventCapture" in code
        assert "SimpleEventCaptureFromBase" in code

        # Check presence of usage guide
        assert "// USAGE GUIDE" in code

    def _create_mock_property(self, name: str, property_type: str, required: bool = False) -> MagicMock:
        """Create a mock SchemaPropertyGroupProperty for testing"""
        prop = MagicMock()
        prop.name = name
        prop.property_type = property_type
        prop.is_required = required
        return prop


class TestGolangGeneratorAPI(APIBaseTest):
    """Test the API endpoint integration"""

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
    def test_golang_endpoint_success(self, mock_report):
        """Test that the golang endpoint returns valid code"""
        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/golang")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        # Check response structure
        assert "content" in data
        assert "event_count" in data
        assert "schema_hash" in data
        assert "generator_version" in data

        # Check code content
        code = data["content"]
        assert "package typed" in code
        assert "FileDownloadedCapture" in code
        assert "UserSignedUpCapture" in code

        # Check specific generated functions
        assert "type FileDownloadedOption" in code
        assert "func FileDownloadedWithFileExtension" in code
        assert "FileDownloadedCaptureFromBase" in code

        # Verify telemetry was called
        self._test_telemetry_called(mock_report)

    def test_golang_endpoint_excludes_non_whitelisted_system_events(self):
        # $autocapture should be excluded
        # $pageview is whitelisted and should be included
        EventDefinition.objects.create(team=self.team, project=self.project, name="$autocapture")
        EventDefinition.objects.create(team=self.team, project=self.project, name="$pageview")

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/golang")

        code = response.json()["content"]
        assert "Autocapture" not in code
        assert "Pageview" in code

    @patch("posthog.api.event_definition_generators.base.report_user_action")
    def test_golang_endpoint_handles_no_events(self, mock_report):
        # Delete all events to test this behaviour
        EventDefinition.objects.filter(team=self.team).delete()

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/golang")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["event_count"] == 0
        assert "package typed" in data["content"]

        # Verify telemetry was called herre
        self._test_telemetry_called(mock_report)

    def test_golang_code_compiles(self):
        """
        This test:
        1. Creates event definitions with schemas
        2. Generates Go code via the API endpoint
        3. Creates a test Go file that uses the generated types
        4. Runs Go compiler to verify no errors

        This ensures the generated code is syntactically correct and type-safe.
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

            response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/golang")
            assert response.status_code == status.HTTP_200_OK
            go_content = response.json()["content"]

            subprocess.run(["go", "mod", "init", "testmodule"], cwd=str(tmpdir_path), check=True, capture_output=True)
            # Install posthog-go dependency
            install_result = subprocess.run(
                ["go", "get", "github.com/posthog/posthog-go"],
                cwd=str(tmpdir_path),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if install_result.returncode != 0:
                self.fail(
                    f"Failed to install posthog-go dependency:\n"
                    f"STDOUT: {install_result.stdout}\n"
                    f"STDERR: {install_result.stderr}"
                )

            # Write generated types
            typed_dir = tmpdir_path / "typed"
            typed_dir.mkdir()
            typed_file = typed_dir / "event_definitions.go"
            typed_file.write_text(go_content)

            # Create test file that uses the generated code
            test_file = tmpdir_path / "main.go"
            test_file.write_text(
                """package main

import (
	"time"
	"testmodule/typed"
	"github.com/posthog/posthog-go"
)

func main() {
	// Test 1: Event with required and optional properties
	cap1 := typed.FileDownloadedCapture(
		"user_123",      // distinct_id (required)
		time.Now(),      // downloaded_at (required)
		"document.pdf",  // file_name (required)
		1024,            // file_size (required)
		typed.FileDownloadedWithFileExtension("pdf"), // optional
		typed.FileDownloadedWithExtraProps(posthog.Properties{
			"custom_field": "custom_value",
		}),
	)
	_ = cap1

	// Test 2: Event with only required properties
	cap2 := typed.UserSignedUpCapture(
		"user_456",
		"user@example.com", // email (required)
		"premium",          // plan (required)
	)
	_ = cap2

	// Test 3: CaptureFromBase extending an existing capture
	base := posthog.Capture{
		DistinctId: "user_789",
		Properties: posthog.Properties{"source": "web"},
	}
	cap3 := typed.FileDownloadedCaptureFromBase(
		base,
		time.Now(),
		"image.png",
		2048,
	)
	_ = cap3

	// Test 4: Event with special characters in name
	cap4 := typed.UserEventWithQuotesCapture(
		"user_999",
		"value", // prop'with"quotes (required)
	)
	_ = cap4
}
"""
            )

            # Run Go compiler
            build_result = subprocess.run(
                ["go", "build", "-o", "test", "main.go"],
                cwd=str(tmpdir_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Assert compilation succeeded
            assert build_result.returncode == 0, f"Go compilation failed. This indicates the generated code is invalid.\n\n" f"STDOUT:\n{build_result.stdout}\n\n" f"STDERR:\n{build_result.stderr}\n\n" f"Generated Go file:\n{go_content}"

    def _test_telemetry_called(self, mock_report) -> None:
        # Verify telemetry was called
        assert mock_report.call_count == 1
        call_args = mock_report.call_args
        assert call_args[0][0] == self.user  # user
        assert call_args[0][1] == "event definitions generated"
        telemetry_props = call_args[0][2]
        assert telemetry_props["language"] == "Go"
        assert telemetry_props["team_id"] == self.team.id
        assert telemetry_props["project_id"] == self.project.id
