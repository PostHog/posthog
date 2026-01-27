import json

from posthog.temporal.data_imports.pipelines.common.load import _extract_nested_value


class TestExtractNestedValue:
    def test_extract_from_dict(self):
        """Test extracting a value from a nested dict."""
        row_value = {"updated_at": "2026-01-27T11:43:22.730151+00:00"}
        result = _extract_nested_value(row_value, ["updated_at"])
        assert result == "2026-01-27T11:43:22.730151+00:00"

    def test_extract_from_json_string(self):
        """Test extracting a value from a JSON string."""
        row_value = json.dumps({"updated_at": "2026-01-27T11:43:22.730151+00:00"})
        result = _extract_nested_value(row_value, ["updated_at"])
        assert result == "2026-01-27T11:43:22.730151+00:00"

    def test_extract_deeply_nested(self):
        """Test extracting from deeply nested structure."""
        row_value = {"level1": {"level2": {"level3": "deep_value"}}}
        result = _extract_nested_value(row_value, ["level1", "level2", "level3"])
        assert result == "deep_value"

    def test_extract_deeply_nested_from_json_string(self):
        """Test extracting from deeply nested JSON string."""
        row_value = json.dumps({"level1": {"level2": {"level3": "deep_value"}}})
        result = _extract_nested_value(row_value, ["level1", "level2", "level3"])
        assert result == "deep_value"

    def test_extract_returns_none_for_none_value(self):
        """Test that None input returns None."""
        result = _extract_nested_value(None, ["any_key"])
        assert result is None

    def test_extract_returns_none_for_missing_key(self):
        """Test that missing key returns None."""
        row_value = {"other_key": "value"}
        result = _extract_nested_value(row_value, ["missing_key"])
        assert result is None

    def test_extract_returns_none_for_missing_nested_key(self):
        """Test that missing nested key returns None."""
        row_value = {"level1": {"level2": "value"}}
        result = _extract_nested_value(row_value, ["level1", "missing"])
        assert result is None

    def test_extract_returns_none_for_invalid_json(self):
        """Test that invalid JSON returns None."""
        row_value = "not valid json"
        result = _extract_nested_value(row_value, ["any_key"])
        assert result is None

    def test_extract_returns_none_when_traversing_non_dict(self):
        """Test that traversing through a non-dict returns None."""
        row_value = {"level1": "not_a_dict"}
        result = _extract_nested_value(row_value, ["level1", "level2"])
        assert result is None
