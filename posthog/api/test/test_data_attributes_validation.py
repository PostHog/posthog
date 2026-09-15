from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import exceptions

from posthog.api.project import ProjectBackwardCompatSerializer
from posthog.api.team import TeamSerializer, validate_data_attributes


class TestDataAttributesValidation(SimpleTestCase):
    @parameterized.expand(
        [
            # A string passes the model's JSONField, then reaches the settings page as a value the
            # attribute select cannot render, which locks the team out of the only control that fixes it.
            ("a_string", "data-attr"),
            ("a_dict", {"0": "data-attr"}),
            ("a_number", 1),
            ("a_list_with_a_number", ["data-attr", 1]),
            ("a_list_with_none", [None]),
        ]
    )
    def test_rejects_values_that_are_not_a_list_of_strings(self, _name, value):
        with self.assertRaises(exceptions.ValidationError):
            validate_data_attributes(value)

    @parameterized.expand(
        [
            ("empty_list", []),
            ("one_attribute", ["data-attr"]),
            ("several_attributes", ["data-attr", "data-cy"]),
        ]
    )
    def test_accepts_a_list_of_strings(self, _name, value):
        assert validate_data_attributes(value) == value

    @parameterized.expand([("team", TeamSerializer), ("project", ProjectBackwardCompatSerializer)])
    def test_serializer_wires_up_the_validator(self, _name, serializer_class):
        serializer = serializer_class(data={"data_attributes": "data-attr"}, partial=True)

        assert not serializer.is_valid()
        assert "data_attributes" in serializer.errors
