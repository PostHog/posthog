from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    CohortPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
)

from posthog.session_recordings.queries.utils import expand_test_account_filters


def _team_with_filters(filters: list) -> MagicMock:
    team = MagicMock()
    team.test_account_filters = filters
    team.pk = 1
    return team


class TestExpandTestAccountFilters:
    @parameterized.expand(
        [
            (
                "person filter",
                {"key": "email", "value": ["bla"], "operator": "exact", "type": "person"},
                PersonPropertyFilter,
            ),
            (
                "event filter",
                {"key": "is_internal_user", "value": ["false"], "operator": "exact", "type": "event"},
                EventPropertyFilter,
            ),
            (
                "group filter",
                {"key": "org", "value": ["ph"], "operator": "exact", "type": "group", "group_type_index": 0},
                GroupPropertyFilter,
            ),
            (
                "hogql filter",
                {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
                HogQLPropertyFilter,
            ),
            (
                "cohort filter",
                {"key": "id", "value": 1, "type": "cohort"},
                CohortPropertyFilter,
            ),
            (
                "untyped filter defaults to event",
                {"key": "is_internal_user", "value": ["false"], "operator": "exact"},
                EventPropertyFilter,
            ),
        ]
    )
    def test_known_filter_types_are_expanded(self, _name: str, filter_dict: dict, expected_type: type) -> None:
        team = _team_with_filters([filter_dict])
        result = expand_test_account_filters(team)
        assert len(result) == 1
        assert isinstance(result[0], expected_type)

    def test_string_entry_is_skipped_without_crashing(self) -> None:
        # A stray non-dict entry in test_account_filters used to crash the recordings
        # list endpoint with AttributeError: 'str' object has no attribute 'get'.
        team = _team_with_filters(
            [
                "this is not a dict",
                {"key": "email", "value": ["bla"], "operator": "exact", "type": "person"},
            ]
        )
        result = expand_test_account_filters(team)
        assert len(result) == 1
        assert isinstance(result[0], PersonPropertyFilter)

    @parameterized.expand(
        [
            ("string", "not a dict"),
            ("none", None),
            ("integer", 42),
            ("list", ["nested", "list"]),
        ]
    )
    def test_non_dict_entries_are_skipped(self, _name: str, bad_entry) -> None:
        team = _team_with_filters([bad_entry])
        result = expand_test_account_filters(team)
        assert result == []

    def test_empty_filters_returns_empty_list(self) -> None:
        team = _team_with_filters([])
        assert expand_test_account_filters(team) == []
