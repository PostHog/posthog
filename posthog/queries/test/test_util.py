from datetime import UTC, date, datetime

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.queries.util import correct_result_for_sampling, get_earliest_timestamp


class TestQueriesUtil(TestCase):
    def test_correct_resullt_for_sampling(self):
        res = correct_result_for_sampling(1, 0.1, None)
        self.assertEqual(res, 10)

        res = correct_result_for_sampling(1, 0.01, None)
        self.assertEqual(res, 100)

        res = correct_result_for_sampling(1, None, None)
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "max")
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "p90_count_per_actor")
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "sum")
        self.assertEqual(res, 100)

    @parameterized.expand(
        [
            ("date", date(2024, 3, 21), datetime(2024, 3, 21, 0, 0, 0, tzinfo=UTC)),
            (
                "datetime_passthrough",
                datetime(2024, 3, 21, 13, 45, 12, tzinfo=UTC),
                datetime(2024, 3, 21, 13, 45, 12, tzinfo=UTC),
            ),
        ]
    )
    def test_get_earliest_timestamp_coerces_date_to_datetime(self, _name, returned, expected):
        # ClickHouse may hand back a `date` for some teams; downstream interval alignment needs a `datetime`.
        with patch("posthog.queries.util.insight_sync_execute", return_value=[[returned]]):
            result = get_earliest_timestamp(1)

        self.assertIsInstance(result, datetime)
        self.assertEqual(result, expected)
