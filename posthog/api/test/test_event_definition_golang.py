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
        self.assertEqual(
            expected_output,
            result,
            f"{name} failed: Expected '{event_name}' to convert to '{expected_output}', got '{result}'",
        )

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
        self.assertEqual(
            expected_output,
            result,
            f"{name} failed: Expected '{input_name}' to convert to '{expected_output}', got '{result}'",
        )

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
        self.assertEqual(
            expected_output,
            result,
            f"{name} failed: Expected '{input_name}' to convert to '{expected_output}', got '{result}'",
        )

    def test_get_unique_name(self):
        """Test collision handling in parameter name generation"""
        used_names: set[str] = set()

        # First usage - no collision
        name1 = self.generator._get_unique_name("fileName", used_names)
        self.assertEqual(name1, "fileName")
        self.assertIn("fileName", used_names)

        # Second usage of same base - should get suffix
        name2 = self.generator._get_unique_name("fileName", used_names)
        self.assertEqual(name2, "fileName2")
        self.assertIn("fileName2", used_names)

        # Third usage
        name3 = self.generator._get_unique_name("fileName", used_names)
        self.assertEqual(name3, "fileName3")

    def test_generate_event_without_properties(self):
        """Test code generation for event without properties"""
        code = self.generator._generate_event_without_properties("simple_click")
        self.assertEqual(
            """// SimpleClickCapture creates a capture for the "simple_click" event.
// This event has no defined schema properties.
func SimpleClickCapture(distinctId string, properties ...posthog.Properties) posthog.Capture {
	props := posthog.Properties{}
	for _, p := range properties {
		for k, v := range p {
			props[k] = v
		}
	}

	return posthog.Capture{
		DistinctId: distinctId,
		Event:      "simple_click",
		Properties: props,
	}
}

// SimpleClickCaptureFromBase creates a posthog.Capture for the "simple_click" event
// starting from an existing base capture. The event name is overridden, and
// any additional properties can be passed via the properties parameter.
func SimpleClickCaptureFromBase(base posthog.Capture, properties ...posthog.Properties) posthog.Capture {
\tprops := posthog.Properties{}
\tfor _, p := range properties {
\t\tfor k, v := range p {
\t\t\tprops[k] = v
\t\t}
\t}

\tbase.Event = "simple_click"
\tif base.Properties == nil {
\t\tbase.Properties = posthog.Properties{}
\t}
\tbase.Properties = base.Properties.Merge(props)

\treturn base
}""",
            code.strip(),
        )

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
        self.assertEqual(
            """// FileUploadedOption configures optional properties for a "file_uploaded" capture.
type FileUploadedOption func(*posthog.Capture)

// FileUploadedWithIsActive sets the "is_active" property on a "file_uploaded" event.
func FileUploadedWithIsActive(isActive bool) FileUploadedOption {
	return func(c *posthog.Capture) {
		if c.Properties == nil {
			c.Properties = posthog.Properties{}
		}
		c.Properties["is_active"] = isActive
	}
}

// FileUploadedWithMetadata sets the "metadata" property on a "file_uploaded" event.
func FileUploadedWithMetadata(metadata map[string]interface{}) FileUploadedOption {
	return func(c *posthog.Capture) {
		if c.Properties == nil {
			c.Properties = posthog.Properties{}
		}
		c.Properties["metadata"] = metadata
	}
}

// FileUploadedWithTags sets the "tags" property on a "file_uploaded" event.
func FileUploadedWithTags(tags []interface{}) FileUploadedOption {
	return func(c *posthog.Capture) {
		if c.Properties == nil {
			c.Properties = posthog.Properties{}
		}
		c.Properties["tags"] = tags
	}
}

// FileUploadedWithExtraProps adds additional properties to a "file_uploaded" event.
func FileUploadedWithExtraProps(props posthog.Properties) FileUploadedOption {
	return func(c *posthog.Capture) {
		if c.Properties == nil {
			c.Properties = posthog.Properties{}
		}
		for k, v := range props {
			c.Properties[k] = v
		}
	}
}

// FileUploadedCapture is a wrapper for the "file_uploaded" event.
// It manages the creation of the `posthog.Capture`. If you need control over this, please make use of
// the FileUploadedCaptureFromBase function.
// Required properties from the schema are explicit parameters; optional properties
// should be passed via FileUploadedWith* option functions.
func FileUploadedCapture(
	distinctId string,
	createdAt time.Time,
	fileName string,
	fileSize float64,
	options ...FileUploadedOption,
) posthog.Capture {
	props := posthog.Properties{
		"created_at": createdAt,
		"file_name": fileName,
		"file_size": fileSize,
	}

	c := posthog.Capture{
		DistinctId: distinctId,
		Event:      "file_uploaded",
		Properties: props,
	}

	for _, opt := range options {
		opt(&c)
	}

	return c
}

// FileUploadedCaptureFromBase creates a posthog.Capture for the "file_uploaded" event
// starting from an existing base capture. The event name is overridden, and
// required properties from the schema are merged on top. Optional properties
// should be passed via FileUploadedWith* option functions.
func FileUploadedCaptureFromBase(
	base posthog.Capture,
	createdAt time.Time,
	fileName string,
	fileSize float64,
	options ...FileUploadedOption,
) posthog.Capture {
	props := posthog.Properties{
		"created_at": createdAt,
		"file_name": fileName,
		"file_size": fileSize,
	}

	base.Event = "file_uploaded"
	if base.Properties == nil {
		base.Properties = posthog.Properties{}
	}
	base.Properties = base.Properties.Merge(props)

	for _, opt := range options {
		opt(&base)
	}

	return base
}""",
            code.strip(),
        )

    def test_generate_event_with_quoted_and_escaped_properties(self):
        props = [
            self._create_mock_property("esc'ap\"eing", "String", required=True),
        ]

        code = self.generator._generate_event_with_properties("creative_naming", props)  # type: ignore[arg-type]
        self.assertEqual(
            """// CreativeNamingOption configures optional properties for a "creative_naming" capture.
type CreativeNamingOption func(*posthog.Capture)

// CreativeNamingWithExtraProps adds additional properties to a "creative_naming" event.
func CreativeNamingWithExtraProps(props posthog.Properties) CreativeNamingOption {
	return func(c *posthog.Capture) {
		if c.Properties == nil {
			c.Properties = posthog.Properties{}
		}
		for k, v := range props {
			c.Properties[k] = v
		}
	}
}

// CreativeNamingCapture is a wrapper for the "creative_naming" event.
// It manages the creation of the `posthog.Capture`. If you need control over this, please make use of
// the CreativeNamingCaptureFromBase function.
// Required properties from the schema are explicit parameters; optional properties
// should be passed via CreativeNamingWith* option functions.
func CreativeNamingCapture(
	distinctId string,
	escApEing string,
	options ...CreativeNamingOption,
) posthog.Capture {
	props := posthog.Properties{
		"esc'ap\\"eing": escApEing,
	}

	c := posthog.Capture{
		DistinctId: distinctId,
		Event:      "creative_naming",
		Properties: props,
	}

	for _, opt := range options {
		opt(&c)
	}

	return c
}

// CreativeNamingCaptureFromBase creates a posthog.Capture for the "creative_naming" event
// starting from an existing base capture. The event name is overridden, and
// required properties from the schema are merged on top. Optional properties
// should be passed via CreativeNamingWith* option functions.
func CreativeNamingCaptureFromBase(
	base posthog.Capture,
	escApEing string,
	options ...CreativeNamingOption,
) posthog.Capture {
	props := posthog.Properties{
		"esc'ap\\"eing": escApEing,
	}

	base.Event = "creative_naming"
	if base.Properties == nil {
		base.Properties = posthog.Properties{}
	}
	base.Properties = base.Properties.Merge(props)

	for _, opt := range options {
		opt(&base)
	}

	return base
}""",
            code.strip(),
        )

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
        self.assertIn("// Code generated by PostHog - DO NOT EDIT", code)
        self.assertIn("package typed", code)
        self.assertIn('"github.com/posthog/posthog-go"', code)
        self.assertNotIn('"time"', code, "time should not be imported as we do not have a DateTime property.")

        # Check event code
        self.assertIn("SimpleEventOption", code)
        self.assertIn("SimpleEventWithCount", code)
        self.assertIn("SimpleEventWithExtraProps", code)
        self.assertIn("SimpleEventCapture", code)
        self.assertIn("SimpleEventCaptureFromBase", code)

        # Check presence of usage guide
        self.assertIn("// USAGE GUIDE", code)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        # Check response structure
        self.assertIn("content", data)
        self.assertIn("event_count", data)
        self.assertIn("schema_hash", data)
        self.assertIn("generator_version", data)

        # Check code content
        code = data["content"]
        self.assertIn("package typed", code)
        self.assertIn("FileDownloadedCapture", code)
        self.assertIn("UserSignedUpCapture", code)

        # Check specific generated functions
        self.assertIn("type FileDownloadedOption", code)
        self.assertIn("func FileDownloadedWithFileExtension", code)
        self.assertIn("FileDownloadedCaptureFromBase", code)

        # Verify telemetry was called
        self._test_telemetry_called(mock_report)

    def test_golang_endpoint_excludes_non_whitelisted_system_events(self):
        # $autocapture should be excluded
        # $pageview is whitelisted and should be included
        EventDefinition.objects.create(team=self.team, project=self.project, name="$autocapture")
        EventDefinition.objects.create(team=self.team, project=self.project, name="$pageview")

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/golang")

        code = response.json()["content"]
        self.assertNotIn("Autocapture", code)
        self.assertIn("Pageview", code)

    @patch("posthog.api.event_definition_generators.base.report_user_action")
    def test_golang_endpoint_handles_no_events(self, mock_report):
        # Delete all events to test this behaviour
        EventDefinition.objects.filter(team=self.team).delete()

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/golang")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["event_count"], 0)
        self.assertIn("package typed", data["content"])

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
            self.assertEqual(response.status_code, status.HTTP_200_OK)
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
            self.assertEqual(
                build_result.returncode,
                0,
                f"Go compilation failed. This indicates the generated code is invalid.\n\n"
                f"STDOUT:\n{build_result.stdout}\n\n"
                f"STDERR:\n{build_result.stderr}\n\n"
                f"Generated Go file:\n{go_content}",
            )

    def _test_telemetry_called(self, mock_report) -> None:
        # Verify telemetry was called
        self.assertEqual(mock_report.call_count, 1)
        call_args = mock_report.call_args
        self.assertEqual(call_args[0][0], self.user)  # user
        self.assertEqual(call_args[0][1], "event definitions generated")
        telemetry_props = call_args[0][2]
        self.assertEqual(telemetry_props["language"], "Go")
        self.assertEqual(telemetry_props["team_id"], self.team.id)
        self.assertEqual(telemetry_props["project_id"], self.project.id)
