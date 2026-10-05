import pytest

from products.actions.backend.api.action import ActionStepJSONSerializer


class TestActionStepRegexRepro:
    """Repro for #96347: action step regexes are accepted with no validation."""

    @pytest.mark.parametrize(
        "field,matching",
        [("url", "url_matching"), ("href", "href_matching"), ("text", "text_matching")],
    )
    def test_invalid_regex_is_rejected(self, field, matching):
        # RE2 (ClickHouse) cannot compile a trailing backslash
        data = {"event": "$pageview", field: "/shardlibrary/\\d+\\", matching: "regex"}
        serializer = ActionStepJSONSerializer(data=data)
        assert not serializer.is_valid(), f"invalid {field} regex was accepted"
        assert field in serializer.errors

    @pytest.mark.parametrize(
        "field,matching",
        [("url", "url_matching"), ("href", "href_matching"), ("text", "text_matching")],
    )
    def test_valid_regex_is_accepted(self, field, matching):
        data = {"event": "$pageview", field: "/shardlibrary/\\d+", matching: "regex"}
        serializer = ActionStepJSONSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.parametrize(
        "field,matching",
        [("url", "url_matching"), ("href", "href_matching"), ("text", "text_matching")],
    )
    @pytest.mark.parametrize("non_regex", ["exact", "contains"])
    def test_non_regex_matching_unaffected(self, field, matching, non_regex):
        data = {"event": "$pageview", field: "/shardlibrary/\\d+\\", matching: non_regex}
        serializer = ActionStepJSONSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_invalid_regex_is_not_logged(self, capfd):
        data = {"event": "$pageview", "url": "/token-abc123/\\d+\\", "url_matching": "regex"}
        serializer = ActionStepJSONSerializer(data=data)
        assert not serializer.is_valid()
        _, err = capfd.readouterr()
        assert "token-abc123" not in err
