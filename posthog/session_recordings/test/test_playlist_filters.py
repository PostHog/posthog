from django.test.testcases import SimpleTestCase

from parameterized import parameterized

from posthog.schema import FilterLogicalOperator, RecordingPropertyFilter

from posthog.session_recordings.playlist_filters import convert_filters_to_recordings_query


def _visited_page(value: str) -> dict:
    return {"type": "recording", "key": "visited_page", "value": value, "operator": "icontains"}


def _filters(outer_type: str, inner_type: str, values: list[dict]) -> dict:
    return {
        "date_from": "-30d",
        "filter_test_accounts": False,
        "filter_group": {"type": outer_type, "values": [{"type": inner_type, "values": values}]},
    }


class TestConvertFiltersToRecordingsQuery(SimpleTestCase):
    @parameterized.expand(
        [
            # "match any" set on the inner group while the outer stays AND must still produce OR
            ("inner_or", "AND", "OR", FilterLogicalOperator.OR_),
            ("all_and", "AND", "AND", FilterLogicalOperator.AND_),
            ("outer_or", "OR", "AND", FilterLogicalOperator.OR_),
        ]
    )
    def test_operand_is_or_when_any_group_is_or(self, _name, outer, inner, expected):
        query = convert_filters_to_recordings_query(_filters(outer, inner, [_visited_page("/cart")]))
        assert query.operand == expected

    def test_visited_page_becomes_recording_property_not_event(self):
        filters = _filters("OR", "OR", [_visited_page("/cart"), _visited_page("/orders")])
        query = convert_filters_to_recordings_query(filters)
        assert query.events == []
        props = query.properties or []
        assert len(props) == 2
        assert all(isinstance(p, RecordingPropertyFilter) and p.key == "visited_page" for p in props)

    def test_nested_filters_are_flattened(self):
        # Filters nested one extra level deep must still be extracted, not dropped
        filters = {
            "date_from": "-30d",
            "filter_group": {
                "type": "AND",
                "values": [{"type": "OR", "values": [{"type": "AND", "values": [_visited_page("/cart")]}]}],
            },
        }
        query = convert_filters_to_recordings_query(filters)
        assert len(query.properties or []) == 1
        assert query.operand == FilterLogicalOperator.OR_

    @parameterized.expand(
        [
            ("or_three_levels_down", "OR", FilterLogicalOperator.OR_),
            ("deep_all_and", "AND", FilterLogicalOperator.AND_),
        ]
    )
    def test_operand_derivation_through_deep_nesting(self, _name, deepest_type, expected):
        filters = {
            "filter_group": {
                "type": "AND",
                "values": [{"type": "AND", "values": [{"type": deepest_type, "values": [_visited_page("/cart")]}]}],
            },
        }
        query = convert_filters_to_recordings_query(filters)
        assert query.operand == expected
