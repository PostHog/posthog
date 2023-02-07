from freezegun import freeze_time

from posthog.models.filters.filter import Filter
from posthog.queries.query_date_range import QueryDateRange
from posthog.test.base import APIBaseTest


class TestQueryDateRange(APIBaseTest):
    def test_parsed_date(self):

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-48h",
                    "interval": "day",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

            query_date_range = QueryDateRange(filter=filter, team=self.team, should_round=False)
            parsed_date_from, date_from_params = query_date_range.date_from
            parsed_date_to, date_to_params = query_date_range.date_to

        self.assertEqual(
            parsed_date_from % date_from_params,
            "AND toDateTime(timestamp, 'UTC') >= toDateTime(2021-08-23 00:00:00, UTC)",
        )
        self.assertEqual(
            parsed_date_to % date_to_params, "AND toDateTime(timestamp, 'UTC') <= toDateTime(2021-08-25 23:59:59, UTC)"
        )

    def test_parsed_date_hour(self):

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-48h",
                    "interval": "hour",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

            query_date_range = QueryDateRange(filter=filter, team=self.team, should_round=False)
            parsed_date_from, date_from_params = query_date_range.date_from
            parsed_date_to, date_to_params = query_date_range.date_to

        self.assertEqual(
            parsed_date_from % date_from_params,
            "AND toDateTime(timestamp, 'UTC') >= toDateTime(2021-08-23 00:00:00, UTC)",
        )
        self.assertEqual(
            parsed_date_to % date_to_params, "AND toDateTime(timestamp, 'UTC') <= toDateTime(2021-08-25 00:01:00, UTC)"
        )  # ensure last hour is included

    def test_parsed_date_middle_of_hour(self):

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "2021-08-23 05:00:00",
                    "date_to": "2021-08-26 07:00:00",
                    "interval": "hour",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

            query_date_range = QueryDateRange(filter=filter, team=self.team, should_round=False)
            parsed_date_from, date_from_params = query_date_range.date_from
            parsed_date_to, date_to_params = query_date_range.date_to

        self.assertEqual(
            parsed_date_from % date_from_params,
            "AND toDateTime(timestamp, 'UTC') >= toDateTime(2021-08-23 05:00:00, UTC)",
        )
        self.assertEqual(
            parsed_date_to % date_to_params, "AND toDateTime(timestamp, 'UTC') <= toDateTime(2021-08-26 07:00:00, UTC)"
        )  # ensure last hour is included

    def test_parsed_date_week_rounded(self):

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-7d",
                    "interval": "week",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

            query_date_range = QueryDateRange(filter=filter, team=self.team)
            parsed_date_from, date_from_params = query_date_range.date_from
            parsed_date_to, date_to_params = query_date_range.date_to

        self.assertEqual(
            parsed_date_from % date_from_params,
            "AND toDateTime(timestamp, 'UTC') >= toStartOfWeek(toDateTime(2021-08-18 00:00:00, UTC), 0)",
        )
        self.assertEqual(
            parsed_date_to % date_to_params, "AND toDateTime(timestamp, 'UTC') <= toDateTime(2021-08-25 23:59:59, UTC)"
        )

    def test_interval_annotation(self):
        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-48h",
                    "interval": "day",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

        query_date_range = QueryDateRange(filter=filter, team=self.team)

        self.assertEquals(query_date_range.interval_annotation, "toStartOfDay")

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-48h",
                    "interval": "week",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

        query_date_range = QueryDateRange(filter=filter, team=self.team)

        self.assertEquals(query_date_range.interval_annotation, "toStartOfWeek")

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-48h",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )

        query_date_range = QueryDateRange(filter=filter, team=self.team)

        self.assertEquals(query_date_range.interval_annotation, "toStartOfDay")

        with freeze_time("2021-08-25T00:00:00.000Z"):
            filter = Filter(
                data={
                    "date_from": "-48h",
                    "interval": "bad",
                    "events": [{"id": "sign up"}, {"id": "no events"}],
                }
            )
        # filter handling will throw not the class
        with self.assertRaises(ValueError) as _:
            query_date_range = QueryDateRange(filter=filter, team=self.team)
            query_date_range.interval_annotation
