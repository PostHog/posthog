from posthog.models.filters.path_filter import PathFilter
from posthog.test.base import APIBaseTest


class TestBase(APIBaseTest):
    def test_determine_compared_filter(self):
        from posthog.queries.base import determine_compared_filter

        filter = PathFilter(data={"date_from": "2020-05-22", "date_to": "2020-05-29"})
        compared_filter = determine_compared_filter(filter)

        self.assertIsInstance(compared_filter, PathFilter)
        self.assertDictContainsSubset({"date_from": "2020-05-15", "date_to": "2020-05-22",}, compared_filter.to_dict())
