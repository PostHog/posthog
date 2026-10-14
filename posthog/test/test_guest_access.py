from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.guest_access import QueryReferences, extract_query_references


class TestExtractQueryReferences(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "cohort filter in a series",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "properties": [{"type": "cohort", "key": "id", "value": 7}]}],
                    },
                },
                QueryReferences(cohort_ids=frozenset({7}), action_ids=frozenset()),
            ),
            (
                "actions node",
                {"kind": "FunnelsQuery", "series": [{"kind": "ActionsNode", "id": 3}]},
                QueryReferences(cohort_ids=frozenset(), action_ids=frozenset({3})),
            ),
            (
                "cohort breakdown",
                {
                    "kind": "TrendsQuery",
                    "series": [],
                    "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [5, "all"]},
                },
                QueryReferences(cohort_ids=frozenset({5}), action_ids=frozenset()),
            ),
            (
                "hogql text",
                {"kind": "HogQLQuery", "query": "select inCohort(9)"},
                QueryReferences(cohort_ids=frozenset(), action_ids=frozenset()),
            ),
            ("no query", None, QueryReferences(cohort_ids=frozenset(), action_ids=frozenset())),
        ]
    )
    def test_extracts_structured_references(self, _name: str, query: Any, expected: QueryReferences) -> None:
        assert extract_query_references(query) == expected
