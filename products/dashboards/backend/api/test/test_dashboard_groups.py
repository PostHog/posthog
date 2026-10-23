from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.api.dashboard import _stored_groups


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
        assert _stored_groups(customization) == expected
