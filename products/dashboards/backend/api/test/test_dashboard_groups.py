from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.api.dashboard import _valid_groups

DEFAULTS = {"collapsed": False, "tint": True, "rail": None}


class TestValidGroups(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_customization", None, {}),
            (
                "group_titles_saved_before_groups_existed",
                {"group_titles": {"plans": "Pricing plans"}},
                {"plans": {"title": "Pricing plans", **DEFAULTS}},
            ),
            (
                "groups_win_over_group_titles",
                {
                    "group_titles": {"plans": "Old title", "regions": "Regions"},
                    "groups": {"plans": {"title": "Plans", "rail": "green"}},
                },
                {
                    "plans": {**DEFAULTS, "title": "Plans", "rail": "green"},
                    "regions": {"title": "Regions", **DEFAULTS},
                },
            ),
            (
                "padded_and_blank_keys",
                {"groups": {" plans ": {"title": "Pricing plans"}, "   ": {"title": "Blank"}}},
                {"plans": {"title": "Pricing plans", **DEFAULTS}},
            ),
            (
                "invalid_entries_are_dropped",
                {
                    "groups": {
                        "plans": {"rail": "pink"},
                        "regions": "Regions",
                        "nulls\u0000": {},
                        "kept": {"collapsed": True, "title": ""},
                    }
                },
                {"kept": {**DEFAULTS, "collapsed": True}},
            ),
        ]
    )
    def test_reads_stored_groups(self, _name: str, customization: Any, expected: dict) -> None:
        assert _valid_groups(customization) == expected
