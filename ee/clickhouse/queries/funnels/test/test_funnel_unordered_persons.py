from datetime import datetime

import pytest

from ee.clickhouse.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest

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
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": "blah",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        with self.assertRaises(ValueError):
            ClickhouseFunnelUnorderedActors(filter, self.team).run()

        filter = filter.with_data({"funnel_step": -1})
        with pytest.raises(ValueError):
            _, _ = ClickhouseFunnelUnorderedActors(filter, self.team).run()

    def test_first_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(35, len(serialized_results))

    def test_last_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": 3,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(5, len(serialized_results))

    def test_second_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(20, len(serialized_results))

    def test_last_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": -3,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(10, len(serialized_results))
