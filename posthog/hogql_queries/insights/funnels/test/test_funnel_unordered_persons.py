from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors_legacy_filters
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d 00:00:00"


class TestFunnelUnorderedStepsPersons(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data_multiple_dropoffs(self):
        events_by_person = {}
        for i in range(5):
            events_by_person[f"user_{i}"] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step three", "timestamp": datetime(2021, 5, 3)},
                {"event": "step two", "timestamp": datetime(2021, 5, 5)},
            ]

        for i in range(5, 15):
            events_by_person[f"user_{i}"] = [
                {"event": "step two", "timestamp": datetime(2021, 5, 1)},
                {"event": "step one", "timestamp": datetime(2021, 5, 3)},
            ]

        for i in range(15, 35):
            events_by_person[f"user_{i}"] = [{"event": "step one", "timestamp": datetime(2021, 5, 1)}]

        journeys_for(events_by_person, self.team)

    def test_invalid_steps(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "unordered",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        with self.assertRaisesMessage(ValueError, "Input should be a valid integer"):
            get_actors_legacy_filters(filters, self.team, funnel_step="blah")  # type: ignore

        with self.assertRaisesMessage(ValueError, "Funnel steps are 1-indexed, so step 0 doesn't exist"):
            get_actors_legacy_filters(filters, self.team, funnel_step=0)

        with self.assertRaisesMessage(ValueError, "The first valid drop-off argument for funnelStep is -2"):
            get_actors_legacy_filters(filters, self.team, funnel_step=-1)

    def test_first_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "unordered",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors_legacy_filters(filters, self.team, funnel_step=1)

        assert 35 == len(results)

    def test_last_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "unordered",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors_legacy_filters(filters, self.team, funnel_step=3)

        assert 5 == len(results)

    def test_second_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "unordered",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors_legacy_filters(filters, self.team, funnel_step=-2)

        assert 20 == len(results)

    def test_last_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "unordered",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors_legacy_filters(filters, self.team, funnel_step=-3)

        assert 10 == len(results)
