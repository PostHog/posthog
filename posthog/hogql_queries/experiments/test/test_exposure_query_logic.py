import pytest

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria

from posthog.hogql_queries.experiments.exposure_query_logic import normalize_to_exposure_criteria


class TestNormalizeToExposureCriteria:
    @pytest.mark.parametrize(
        "input_value,expected_type",
        [
            (None, type(None)),
            (ExperimentExposureCriteria(), ExperimentExposureCriteria),
            ({}, ExperimentExposureCriteria),
            ({"exposure_config": {"event": "test", "properties": []}}, ExperimentExposureCriteria),
        ],
    )
    def test_handles_different_input_types(self, input_value, expected_type):
        result = normalize_to_exposure_criteria(input_value)
        assert isinstance(result, expected_type)

    def test_does_not_mutate_input_dict(self):
        original = {"exposure_config": {"event": "test", "properties": []}}
        original_copy = original.copy()

        normalize_to_exposure_criteria(original)

        # Original dict should remain unchanged
        assert original == original_copy
        assert isinstance(original["exposure_config"], dict)

    def test_converts_nested_exposure_config(self):
        input_dict = {"exposure_config": {"event": "test_event", "properties": []}}

        result = normalize_to_exposure_criteria(input_dict)

        assert result is not None
        assert isinstance(result.exposure_config, ExperimentEventExposureConfig)
        assert result.exposure_config.event == "test_event"

    def test_preserves_already_typed_object(self):
        typed_criteria = ExperimentExposureCriteria()

        result = normalize_to_exposure_criteria(typed_criteria)

        # Should return the exact same object, not a copy
        assert result is typed_criteria
