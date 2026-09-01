from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import exceptions

from posthog.api.team import TeamSerializer, validate_path_cleaning_filters


class TestPathCleaningFilterValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("uncompilable_regex", [{"regex": "/users/((", "alias": "/users/x"}]),
            ("backreference_out_of_range", [{"regex": "/users/(\\d+)", "alias": "/users/\\2"}]),
            ("backreference_with_no_group", [{"regex": "/users/\\d+", "alias": "/users/\\1"}]),
            ("value_that_is_not_a_list", "not-a-list"),
            # An empty pattern matches everywhere and a missing one reaches ClickHouse as NULL, so
            # both mangle every path the rule touches rather than doing nothing.
            ("empty_regex", [{"regex": "", "alias": "/users/x"}]),
            ("rule_without_a_regex", [{"alias": "/users/<id>"}]),
        ]
    )
    def test_rejects_invalid_rules(self, _name, filters):
        with self.assertRaises(exceptions.ValidationError):
            validate_path_cleaning_filters(filters)

    @parameterized.expand(
        [
            ("valid_backreference", [{"regex": "/users/(\\d+)", "alias": "/users/\\1"}]),
            ("whole_match_reference", [{"regex": "/users/(\\d+)", "alias": "/x/\\0"}]),
            # A doubled backslash is a literal backslash, not a back-reference, so \\1 needs no group.
            ("escaped_backslash_is_literal", [{"regex": "/users/\\d+", "alias": "/users/\\\\1"}]),
            ("static_placeholder_alias", [{"regex": "/users/\\d+", "alias": "/users/<id>"}]),
            ("empty_list", []),
            # re2 reads only ASCII digits as a back-reference, so these are literal text. Matching on
            # str.isdigit() instead crashes on the superscript and misreads the Arabic-Indic digit.
            ("superscript_digit_is_literal", [{"regex": "/users/\\d+", "alias": "/users/\\²"}]),
            ("arabic_indic_digit_is_literal", [{"regex": "/users/\\d+", "alias": "/users/\\٣"}]),
            # Pydantic drops a rule that isn't a dict before the query runs, so it can't corrupt a path.
            ("rule_that_is_not_a_dict", ["not-a-rule"]),
            ("rule_without_an_alias", [{"regex": "/users/\\d+"}]),
        ]
    )
    def test_accepts_valid_rules(self, _name, filters):
        assert validate_path_cleaning_filters(filters) == filters

    def test_serializer_wires_up_the_validator(self):
        serializer = TeamSerializer(
            data={"path_cleaning_filters": [{"regex": "/users/(\\d+)", "alias": "/users/\\2"}]},
            partial=True,
        )
        assert not serializer.is_valid()
        assert "path_cleaning_filters" in serializer.errors
