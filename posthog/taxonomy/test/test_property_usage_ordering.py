import uuid

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.taxonomy.property_usage_ordering import PropertyDefinitionOrdering, UsedProperty, plan_usage_page

USED = [
    UsedProperty(id=uuid.UUID(int=3), name="c", count=1),
    UsedProperty(id=uuid.UUID(int=2), name="b", count=5),
    UsedProperty(id=uuid.UUID(int=1), name="a", count=5),
]
# Three used and three unused definitions match the filters.
TOTAL = 6


class TestPlanUsagePage(SimpleTestCase):
    @parameterized.expand(
        [
            ("most_first_page_is_all_used", PropertyDefinitionOrdering.MOST_QUERIED, 0, 2, ["a", "b"], 0, 0),
            ("most_page_crosses_into_unused", PropertyDefinitionOrdering.MOST_QUERIED, 2, 2, ["c"], 0, 1),
            ("most_page_is_all_unused", PropertyDefinitionOrdering.MOST_QUERIED, 4, 2, [], 1, 2),
            ("most_page_past_the_end", PropertyDefinitionOrdering.MOST_QUERIED, 6, 2, [], 3, 0),
            ("least_first_page_is_all_unused", PropertyDefinitionOrdering.LEAST_QUERIED, 0, 2, [], 0, 2),
            ("least_page_crosses_into_used", PropertyDefinitionOrdering.LEAST_QUERIED, 2, 2, ["c"], 2, 1),
            ("least_last_page_is_all_used", PropertyDefinitionOrdering.LEAST_QUERIED, 4, 2, ["a", "b"], 4, 0),
            ("least_whole_list_in_one_page", PropertyDefinitionOrdering.LEAST_QUERIED, 0, 10, ["c", "a", "b"], 0, 3),
        ]
    )
    def test_splits_the_page_between_used_and_unused(
        self,
        _name: str,
        ordering: PropertyDefinitionOrdering,
        offset: int,
        limit: int,
        expected_used: list[str],
        expected_unused_offset: int,
        expected_unused_limit: int,
    ) -> None:
        plan = plan_usage_page(ordering, USED, TOTAL, offset, limit)

        assert [row.name for row in plan.used] == expected_used
        assert plan.unused_limit == expected_unused_limit
        if expected_unused_limit:
            assert plan.unused_offset == expected_unused_offset
        assert plan.unused_first == (ordering == PropertyDefinitionOrdering.LEAST_QUERIED)
