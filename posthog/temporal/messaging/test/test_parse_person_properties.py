import json

from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import parse_person_properties


class TestParsePersonProperties:
    """Unit tests for parse_person_properties function."""

    def test_parses_valid_json_string(self):
        """Should parse valid JSON string into dict."""
        properties = {"email": "test@example.com", "name": "Test User"}
        properties_raw = json.dumps(properties)

        result = parse_person_properties(properties_raw, "person123")

        assert result == properties

    def test_handles_dict_input(self):
        """Should return dict input as-is."""
        properties = {"email": "test@example.com", "name": "Test User"}

        result = parse_person_properties(properties, "person123")

        assert result == properties

    def test_handles_null_value(self):
        """Should return empty dict for None input."""
        result = parse_person_properties(None, "person123")

        assert result == {}

    def test_handles_empty_string(self):
        """Should return empty dict for empty string and log warning."""
        result = parse_person_properties("", "person123")

        assert result == {}

    def test_handles_invalid_json_string(self):
        """Should return empty dict for invalid JSON and log warning."""
        invalid_json = "{invalid json string"

        result = parse_person_properties(invalid_json, "person123")

        assert result == {}

    def test_handles_json_null_string(self):
        """Should return empty dict for JSON 'null' string."""
        result = parse_person_properties("null", "person123")

        assert result == {}

    def test_handles_empty_json_object_string(self):
        """Should parse empty JSON object string."""
        result = parse_person_properties("{}", "person123")

        assert result == {}

    def test_handles_empty_json_array_string(self):
        """Should return empty dict for JSON array."""
        result = parse_person_properties("[]", "person123")

        assert result == {}

    def test_handles_json_false_string(self):
        """Should return empty dict for JSON 'false' string."""
        result = parse_person_properties("false", "person123")

        assert result == {}

    def test_handles_json_zero_string(self):
        """Should return empty dict for JSON '0' string."""
        result = parse_person_properties("0", "person123")

        assert result == {}

    def test_handles_complex_nested_json(self):
        """Should parse complex nested JSON structure."""
        properties = {
            "email": "test@example.com",
            "metadata": {"source": "api", "tags": ["premium", "enterprise"]},
            "settings": {"notifications": True, "theme": "dark"},
        }
        properties_raw = json.dumps(properties)

        result = parse_person_properties(properties_raw, "person123")

        assert result == properties

    def test_handles_long_invalid_json_string(self):
        """Should handle very long invalid JSON strings without errors."""
        long_invalid_json = "{invalid" + "x" * 200

        result = parse_person_properties(long_invalid_json, "person123")

        assert result == {}

    def test_preserves_unicode_characters(self):
        """Should correctly parse JSON with unicode characters."""
        properties = {"name": "测试用户", "emoji": "🎉", "special": "café"}
        properties_raw = json.dumps(properties, ensure_ascii=False)

        result = parse_person_properties(properties_raw, "person123")

        assert result == properties

    def test_handles_whitespace_string(self):
        """Should return empty dict for whitespace-only string."""
        result = parse_person_properties("   ", "person123")

        assert result == {}

    def test_handles_numeric_string(self):
        """Should return empty dict for numeric string (not valid object JSON)."""
        result = parse_person_properties("42", "person123")

        assert result == {}

    def test_handles_boolean_dict_values(self):
        """Should preserve boolean values in parsed dict."""
        properties = {"is_active": True, "is_verified": False}
        properties_raw = json.dumps(properties)

        result = parse_person_properties(properties_raw, "person123")

        assert result == properties
        assert result["is_active"] is True
        assert result["is_verified"] is False
