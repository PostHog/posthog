from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.constants import MAX_GROUP_TITLE_LENGTH
from products.dashboards.backend.customization import stored_groups, without_default_settings
from products.dashboards.backend.presentation.widget_openapi_serializers import DashboardTileGroupSerializer


class TestStoredGroups(SimpleTestCase):
    # Explicitly typed so mypy doesn't narrow the customization type from the first
    # cases and then reject a later case that mixes value types (str, bool, None).
    cases: list[tuple[str, Any, dict[str, Any]]] = [
        ("no_customization", None, {}),
        (
            "group_titles_saved_before_groups_existed",
            {"group_titles": {"plans": "Pricing plans"}},
            {"plans": {"title": "Pricing plans"}},
        ),
        (
            "group_titles_win_because_only_an_older_server_writes_them",
            {
                "group_titles": {"plans": "New title"},
                "groups": {"plans": {"title": "Old title", "color": "green"}, "regions": {}},
            },
            {"plans": {"title": "New title", "color": "green"}, "regions": {}},
        ),
        (
            "invalid_settings_keep_the_group_title",
            {"group_titles": {"plans": "Plans"}, "groups": {"plans": {"color": "pink"}}},
            {"plans": {"title": "Plans"}},
        ),
        (
            "padded_and_blank_keys",
            {"groups": {" plans ": {"title": "Pricing plans"}, "   ": {"title": "Blank"}}},
            {"plans": {"title": "Pricing plans"}},
        ),
        (
            "invalid_entries_are_dropped",
            {
                "groups": {
                    "plans": {"color": "pink"},
                    "regions": "Regions",
                    "nulls\u0000": {},
                    "kept": {"collapsed": True, "title": ""},
                }
            },
            {"kept": {"collapsed": True}},
        ),
        (
            "settings_equal_to_defaults_are_dropped",
            {"groups": {"plans": {"title": "Plans", "collapsed": False, "color": None}}},
            {"plans": {"title": "Plans"}},
        ),
    ]

    @parameterized.expand(cases)
    def test_reads_stored_groups(self, _name: str, customization: Any, expected: dict) -> None:
        assert stored_groups(customization) == expected

    group_settings_cases: list[tuple[str, Any, dict[str, Any] | None]] = [
        ("padded_title", {"title": "  Plans  "}, {"title": "Plans"}),
        ("number_title", {"title": 5}, {"title": "5"}),
        ("longest_title", {"title": "t" * MAX_GROUP_TITLE_LENGTH}, {"title": "t" * MAX_GROUP_TITLE_LENGTH}),
        ("too_long_title", {"title": "t" * (MAX_GROUP_TITLE_LENGTH + 1)}, None),
        ("null_title", {"title": None}, None),
        ("null_character_title", {"title": "a\u0000b"}, None),
        ("string_collapsed", {"collapsed": "true"}, {"collapsed": True}),
        ("null_collapsed", {"collapsed": None}, None),
        ("unknown_collapsed", {"collapsed": "maybe"}, None),
        ("color", {"color": "red"}, {"color": "red"}),
        ("blank_color", {"color": ""}, None),
        ("unknown_color", {"color": "pink"}, None),
        ("unknown_setting", {"icon": "star"}, {}),
        ("not_an_object", ["Plans"], None),
    ]

    @parameterized.expand(group_settings_cases)
    def test_reads_group_settings_as_the_api_writes_them(
        self, _name: str, settings: Any, expected: dict[str, Any] | None
    ) -> None:
        written = DashboardTileGroupSerializer(data=settings)
        assert (without_default_settings(written.validated_data) if written.is_valid() else None) == expected
        assert stored_groups({"groups": {"plans": settings}}) == ({} if expected is None else {"plans": expected})
