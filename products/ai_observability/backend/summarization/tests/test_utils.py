import pytest

from django.template import TemplateDoesNotExist
from django.utils.safestring import SafeString

from posthog.hogql.property_access_types import RestrictedProperty

from products.ai_observability.backend.summarization.utils import (
    get_summarization_lookup_date_range,
    get_summary_cache_key,
    load_summarization_template,
)
from products.event_definitions.backend.models.property_definition import PropertyDefinition


class TestSummarizationLookupDateRange:
    @pytest.mark.parametrize(
        "date_from,date_to,expected_from,expected_to",
        [
            (None, None, "2026-01-14T12:00:00+00:00", "2026-01-16T12:00:00+00:00"),
            ("-7d", None, "-7d", "2026-01-16T12:00:00+00:00"),
            (None, "2026-02-01", "2026-01-14T12:00:00+00:00", "2026-02-01"),
            ("-7d", "2026-02-01", "-7d", "2026-02-01"),
        ],
    )
    def test_fills_only_missing_bounds_from_event_timestamp(
        self, date_from: str | None, date_to: str | None, expected_from: str, expected_to: str
    ) -> None:
        date_range = get_summarization_lookup_date_range("2026-01-15T12:00:00Z", date_from=date_from, date_to=date_to)

        assert date_range.date_from == expected_from
        assert date_range.date_to == expected_to

    @pytest.mark.parametrize("timestamp", [None, 42, "not-a-timestamp", "2026-02-30T12:00:00Z", "0001-01-01T12:00:00Z"])
    def test_invalid_timestamp_preserves_lookup_defaults(self, timestamp: object) -> None:
        date_range = get_summarization_lookup_date_range(timestamp, date_to="2026-02-01")

        assert date_range.date_from is None
        assert date_range.date_to == "2026-02-01"


class TestSummaryCacheKey:
    def test_scopes_cache_by_effective_restrictions(self) -> None:
        unrestricted_key = get_summary_cache_key(1, "trace", "trace-1")
        assert unrestricted_key == "llm_summary:1:trace:trace-1:minimal:default"
        assert get_summary_cache_key(1, "trace", "trace-1", restricted_properties=[]) == unrestricted_key

        restrictions = [
            RestrictedProperty(name="input", property_type=PropertyDefinition.Type.EVENT),
            RestrictedProperty(name="output", property_type=PropertyDefinition.Type.EVENT),
            RestrictedProperty(name="input", property_type=PropertyDefinition.Type.PERSON),
            RestrictedProperty(name="input", property_type=PropertyDefinition.Type.GROUP),
            RestrictedProperty(name="input", property_type=PropertyDefinition.Type.GROUP, group_type_index=0),
            RestrictedProperty(name="input", property_type=PropertyDefinition.Type.GROUP, group_type_index=1),
        ]
        scoped_keys = {
            get_summary_cache_key(1, "trace", "trace-1", restricted_properties=[restriction])
            for restriction in restrictions
        }
        assert len(scoped_keys) == len(restrictions)
        assert unrestricted_key not in scoped_keys
        assert get_summary_cache_key(
            1, "trace", "trace-1", restricted_properties=restrictions
        ) == get_summary_cache_key(1, "trace", "trace-1", restricted_properties=list(reversed(restrictions)))


class TestLoadSummarizationTemplate:
    def test_loads_user_template_with_context(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "L1: Hello World"},
        )
        assert "Analyze and summarize" in result
        assert "L1: Hello World" in result

    def test_loads_system_minimal_template(self):
        result = load_summarization_template("prompts/system_minimal.djt", {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_loads_system_detailed_template(self):
        result = load_summarization_template("prompts/system_detailed.djt", {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_plain_str_not_safestring(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "test content"},
        )
        assert type(result) is str
        assert not isinstance(result, SafeString)

    def test_handles_special_characters_in_context(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "<script>alert('xss')</script> & \"quotes\""},
        )
        # Since autoescape is False, special chars should remain unescaped
        assert "<script>" in result
        assert "&" in result
        assert '"quotes"' in result

    def test_handles_unicode_in_context(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "Unicode: \u2192 \u2713 \u2717 \u4e2d\u6587"},
        )
        assert "\u2192" in result
        assert "\u2713" in result
        assert "\u4e2d\u6587" in result

    def test_nonexistent_template_raises(self):
        with pytest.raises(TemplateDoesNotExist):
            load_summarization_template("prompts/nonexistent.djt", {})

    def test_empty_context(self):
        result = load_summarization_template("prompts/system_minimal.djt", {})
        assert isinstance(result, str)

    @pytest.mark.parametrize(
        "template_path",
        [
            "prompts/user.djt",
            "prompts/system_minimal.djt",
            "prompts/system_detailed.djt",
        ],
    )
    def test_all_templates_load_without_error(self, template_path):
        result = load_summarization_template(template_path, {"text_repr": "test"})
        assert isinstance(result, str)
        assert len(result) > 0
