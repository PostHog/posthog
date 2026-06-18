from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import Filter
from posthog.models.filters.mixins.funnel import FunnelWindowDaysMixin


class TestFilterMixins(BaseTest):
    def test_funnel_window_days_to_microseconds(self):
        one_day = FunnelWindowDaysMixin.microseconds_from_days(1)
        two_days = FunnelWindowDaysMixin.microseconds_from_days(2)
        three_days = FunnelWindowDaysMixin.microseconds_from_days(3)

        self.assertEqual(86_400_000_000, one_day)
        self.assertEqual(17_2800_000_000, two_days)
        self.assertEqual(259_200_000_000, three_days)

    def test_funnel_window_days_to_milliseconds(self):
        one_day = FunnelWindowDaysMixin.milliseconds_from_days(1)
        self.assertEqual(one_day, 86_400_000)

    # Constructing a Filter with a team eagerly calls simplify(), which parses every
    # entity param — so a malformed value must raise a 400-mapping ValidationError there,
    # not an uncaught JSONDecodeError (which surfaced as a 500 on /api/person/).
    @parameterized.expand(["events", "actions", "data_warehouse_entities", "exclusions"])
    def test_malformed_entity_param_raises_validation_error(self, param: str):
        for malformed in ("undefined", "{not json", "null x"):
            with self.assertRaises(ValidationError):
                Filter(data={param: malformed}, team=self.team)

    def test_valid_json_string_events_param_is_parsed(self):
        filter = Filter(data={"events": '[{"id": "$pageview"}]'}, team=self.team)
        self.assertEqual(len(filter.events), 1)
        self.assertEqual(filter.events[0].id, "$pageview")
