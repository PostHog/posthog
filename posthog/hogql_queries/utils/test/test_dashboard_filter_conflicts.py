from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql_queries.utils.dashboard_filter_conflicts import filters_contradict


class TestFiltersContradict(SimpleTestCase):
    @parameterized.expand(
        [
            # (name, filter_a, filter_b, expected)
            (
                "same exact value is compatible",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                False,
            ),
            (
                "disjoint exact values contradict",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "exact", "value": ["b"]},
                True,
            ),
            (
                "overlapping exact values are compatible",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a", "b"]},
                {"key": "k", "type": "event", "operator": "exact", "value": ["b", "c"]},
                False,
            ),
            (
                "exact contradicts is_not on the same value",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "is_not", "value": ["a"]},
                True,
            ),
            (
                "exact and is_not on different values are compatible",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "is_not", "value": ["b"]},
                False,
            ),
            (
                "exact and is_set stack",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "is_set"},
                False,
            ),
            (
                "exact contradicts is_not_set",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "is_not_set"},
                True,
            ),
            (
                "is_not and is_not_set are compatible (negation matches unset)",
                {"key": "k", "type": "event", "operator": "is_not", "value": ["a"]},
                {"key": "k", "type": "event", "operator": "is_not_set"},
                False,
            ),
            (
                "different keys never contradict",
                {"key": "a", "type": "event", "operator": "exact", "value": ["x"]},
                {"key": "b", "type": "event", "operator": "exact", "value": ["y"]},
                False,
            ),
            (
                "same key on different group types does not contradict",
                {"key": "name", "type": "group", "group_type_index": 0, "operator": "exact", "value": ["x"]},
                {"key": "name", "type": "group", "group_type_index": 1, "operator": "exact", "value": ["y"]},
                False,
            ),
            (
                "cohort filters are never compared",
                {"key": "id", "type": "cohort", "operator": "exact", "value": [1]},
                {"key": "id", "type": "cohort", "operator": "exact", "value": [2]},
                False,
            ),
            (
                "icontains contradicts not_icontains that excludes the needle",
                {"key": "k", "type": "event", "operator": "icontains", "value": ["Goog"]},
                {"key": "k", "type": "event", "operator": "not_icontains", "value": ["goog"]},
                True,
            ),
            (
                "regex contradicts not_regex with the identical pattern",
                {"key": "k", "type": "event", "operator": "regex", "value": ["^a$"]},
                {"key": "k", "type": "event", "operator": "not_regex", "value": ["^a$"]},
                True,
            ),
            (
                "boolean and its lowercase string form are the same value",
                {"key": "k", "type": "event", "operator": "exact", "value": [True]},
                {"key": "k", "type": "event", "operator": "is_not", "value": ["true"]},
                True,
            ),
            (
                "a bare string in place of a filter dict never contradicts",
                {"key": "k", "type": "event", "operator": "exact", "value": ["a"]},
                "utm_source",
                False,
            ),
            (
                "two non-dict entries never contradict",
                "utm_source",
                "utm_medium",
                False,
            ),
        ]
    )
    def test_filters_contradict(self, _name, filter_a, filter_b, expected):
        assert filters_contradict(filter_a, filter_b) is expected
        # Contradiction is symmetric.
        assert filters_contradict(filter_b, filter_a) is expected
