import unittest

from freezegun import freeze_time

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Event
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.person import Person
from posthog.queries.sessions.sessions import Sessions
from posthog.test.base import BaseTest


def sessions_test_factory(sessions, event_factory, person_factory):
    class TestSessions(BaseTest):
        def test_sessions_avg_length(self):
            # make sure out of range event doesn't get included
            with freeze_time("2012-01-01T03:21:34.000Z"):
                event_factory(team=self.team, event="bad action", distinct_id="1")

            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            # 4 minutes
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")

            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            # 2 minutes
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1")
                event_factory(team=self.team, event="4th action", distinct_id="2")

            with freeze_time("2012-01-21T04:01:34.000Z"):
                response = sessions().run(
                    SessionsFilter(
                        data={
                            "session": "avg",
                            "events": [
                                {"id": "1st action"},
                                {"id": "2nd action"},
                                {"id": "3rd action"},
                                {"id": "4th action"},
                            ],
                        }
                    ),
                    self.team,
                )
                with freeze_time("2012-01-21T04:01:34.000Z"):
                    no_entity_response = sessions().run(SessionsFilter(data={"session": "avg"}), self.team,)

            self.assertEqual(response[0]["count"], 3)  # average length of all sessions
            # time series
            self.assertEqual(response[0]["data"][0], 4.0)
            self.assertEqual(response[0]["data"][1], 2.0)
            self.assertEqual(response[0]["labels"][0], "14-Jan-2012")
            self.assertEqual(response[0]["labels"][1], "15-Jan-2012")
            self.assertEqual(response[0]["days"][0], "2012-01-14")
            self.assertEqual(response[0]["days"][1], "2012-01-15")
            self.assertEqual(response[0]["chartLabel"], "Average Session Length (minutes)")
            self.assertEqual(response, no_entity_response)

        def test_sessions_avg_length_interval(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-25T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-25T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1")
                event_factory(team=self.team, event="4th action", distinct_id="2")

            with freeze_time("2012-03-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-03-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-03-15T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-03-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="2")

            # month
            month_response = sessions().run(
                SessionsFilter(
                    data={
                        "date_from": "2012-01-01",
                        "date_to": "2012-04-01",
                        "interval": "month",
                        "session": "avg",
                        "events": [
                            {"id": "1st action"},
                            {"id": "2nd action"},
                            {"id": "3rd action"},
                            {"id": "4th action"},
                        ],
                    }
                ),
                self.team,
            )

            self.assertEqual(month_response[0]["data"][0], 3.0)
            self.assertEqual(month_response[0]["data"][2], 3.0)
            self.assertEqual(month_response[0]["labels"][0], "31-Jan-2012")
            self.assertEqual(month_response[0]["labels"][1], "29-Feb-2012")
            self.assertEqual(month_response[0]["days"][0], "2012-01-31")
            self.assertEqual(month_response[0]["days"][1], "2012-02-29")

            # # week
            week_response = sessions().run(
                SessionsFilter(
                    data={
                        # 2012-01-01 is a Sunday
                        "date_from": "2012-01-01",
                        "date_to": "2012-02-01",
                        "interval": "week",
                        "session": "avg",
                        "events": [
                            {"id": "1st action"},
                            {"id": "2nd action"},
                            {"id": "3rd action"},
                            {"id": "4th action"},
                        ],
                    }
                ),
                self.team,
            )
            self.assertEqual(week_response[0]["data"][1], 4.0)
            self.assertEqual(week_response[0]["data"][3], 2.0)
            self.assertEqual(week_response[0]["labels"][0], "1-Jan-2012")
            self.assertEqual(week_response[0]["labels"][1], "8-Jan-2012")
            self.assertEqual(week_response[0]["days"][0], "2012-01-01")
            self.assertEqual(week_response[0]["days"][1], "2012-01-08")

            # # # hour
            hour_response = sessions().run(
                SessionsFilter(
                    data={
                        "date_from": "2012-03-14",
                        "date_to": "2012-03-16",
                        "interval": "hour",
                        "session": "avg",
                        "events": [
                            {"id": "1st action"},
                            {"id": "2nd action"},
                            {"id": "3rd action"},
                            {"id": "4th action"},
                        ],
                    }
                ),
                self.team,
            )
            self.assertEqual(hour_response[0]["data"][3], 4.0)
            self.assertEqual(hour_response[0]["data"][27], 2.0)
            self.assertEqual(hour_response[0]["labels"][0], "14-Mar-2012 00:00")
            self.assertEqual(hour_response[0]["labels"][1], "14-Mar-2012 01:00")
            self.assertEqual(hour_response[0]["days"][0], "2012-03-14 00:00:00")
            self.assertEqual(hour_response[0]["days"][1], "2012-03-14 01:00:00")

        def test_no_events(self):
            response = sessions().run(
                SessionsFilter(
                    data={"date_from": "2012-01-20", "date_to": "2012-01-30", "interval": "day", "session": "avg",}
                ),
                self.team,
            )
            self.assertEqual(response, [])

        def test_compare(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-25T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-25T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1")
                event_factory(team=self.team, event="4th action", distinct_id="2")
            filter = SessionsFilter(
                data={
                    "date_from": "2012-01-20",
                    "date_to": "2012-01-30",
                    "interval": "day",
                    "compare": True,
                    "session": "avg",
                    "events": [{"id": "1st action"}, {"id": "2nd action"}, {"id": "3rd action"}, {"id": "4th action"}],
                }
            )
            # Run without anything to compare to
            compare_response = sessions().run(filter=filter, team=self.team)

            self.assertEqual(compare_response[0]["data"][5], 2.0)
            self.assertEqual(compare_response[1]["data"][4], 4.0)

        def test_sessions_count_buckets_default(self):
            with freeze_time("2012-01-11T01:25:30.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="2")

            with freeze_time("2012-01-21T01:25:30.000Z"):
                response = sessions().run(SessionsFilter(data={"session": "dist"}), self.team)
                for _, item in enumerate(response):
                    self.assertEqual(item["count"], 0)

        def test_sessions_count_buckets(self):

            # 0 seconds
            with freeze_time("2012-01-11T01:25:30.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="2")
                event_factory(team=self.team, event="1st action", distinct_id="2")
                event_factory(team=self.team, event="1st action", distinct_id="4")
            with freeze_time("2012-01-11T01:25:32.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="4")  # within 0-3 seconds
                event_factory(team=self.team, event="1st action", distinct_id="6")
                event_factory(team=self.team, event="2nd action", distinct_id="7")
            with freeze_time("2012-01-11T01:25:40.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="6")  # within 3-10 seconds
                event_factory(team=self.team, event="2nd action", distinct_id="7")  # within 3-10 seconds

            with freeze_time("2012-01-15T04:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
                event_factory(team=self.team, event="3rd action", distinct_id="4")
            with freeze_time("2012-01-15T05:00:00.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")  # within 10-30 seconds
            with freeze_time("2012-01-15T05:00:20.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="4")  # within 30-60 seconds

            # within 1-3 mins
            with freeze_time("2012-01-17T04:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
                event_factory(team=self.team, event="3rd action", distinct_id="2")
                event_factory(team=self.team, event="3rd action", distinct_id="5")
            with freeze_time("2012-01-17T05:01:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
            with freeze_time("2012-01-17T05:07:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")  # test many events within a range
                event_factory(team=self.team, event="3rd action", distinct_id="2")
                event_factory(team=self.team, event="3rd action", distinct_id="2")
                event_factory(team=self.team, event="3rd action", distinct_id="2")  # within 3-10 mins
                event_factory(team=self.team, event="3rd action", distinct_id="10")

            with freeze_time("2012-01-17T05:20:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="5")  # within 10-30 mins
                event_factory(team=self.team, event="3rd action", distinct_id="9")
                event_factory(team=self.team, event="3rd action", distinct_id="10")
            with freeze_time("2012-01-17T05:40:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="9")
                event_factory(team=self.team, event="3rd action", distinct_id="10")  # within 30-60 mins
            with freeze_time("2012-01-17T05:58:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="9")  # -> within 30-60 mins

            # within 1+ hours
            with freeze_time("2012-01-21T04:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-21T05:20:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-21T05:45:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-21T06:00:30.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")

            response = sessions().run(
                SessionsFilter(
                    data={
                        "date_from": "all",
                        "session": "dist",
                        "events": [
                            {"id": "1st action"},
                            {"id": "2nd action"},
                            {"id": "3rd action"},
                            {"id": "4th action"},
                        ],
                    }
                ),
                self.team,
            )
            compared_response = sessions().run(
                SessionsFilter(
                    data={
                        "date_from": "all",
                        "compare": True,
                        "session": "dist",
                        "events": [
                            {"id": "1st action"},
                            {"id": "2nd action"},
                            {"id": "3rd action"},
                            {"id": "4th action"},
                        ],
                    }
                ),
                self.team,
            )
            self.assertEqual(len(response), 10)
            for index, item in enumerate(response):
                if item["label"] == "30-60 minutes" or item["label"] == "3-10 seconds":
                    self.assertEqual(item["count"], 2)
                    self.assertEqual(compared_response[index]["count"], 2)
                else:
                    self.assertEqual(item["count"], 1)
                    self.assertEqual(compared_response[index]["count"], 1)

        def test_filter_test_accounts(self):
            # 0 seconds
            person_factory(team_id=self.team.pk, distinct_ids=["2"], properties={"email": "test@posthog.com"})
            person_factory(
                team_id=self.team.pk, distinct_ids=["4"],
            )
            with freeze_time("2012-01-11T01:25:30.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="2")
                event_factory(team=self.team, event="1st action", distinct_id="4")
            with freeze_time("2012-01-11T01:31:30.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-11T01:51:30.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="4")

            with freeze_time("2012-01-12T03:40:30.000Z"):
                response = sessions().run(
                    SessionsFilter(
                        data={
                            "date_from": "all",
                            "session": "dist",
                            FILTER_TEST_ACCOUNTS: True,
                            "events": [{"id": "1st action"},],
                        }
                    ),
                    self.team,
                )
                self.assertEqual(response[6]["count"], 0)
                self.assertEqual(response[7]["count"], 1)

                response = sessions().run(
                    SessionsFilter(
                        data={
                            "interval": "day",
                            "session": "avg",
                            FILTER_TEST_ACCOUNTS: True,
                            "events": [{"id": "1st action"},],
                        }
                    ),
                    self.team,
                )
                self.assertEqual(response[0]["data"][6], 26)

    return TestSessions


class DjangoSessionsTest(sessions_test_factory(Sessions, Event.objects.create, Person.objects.create)):  # type: ignore
    pass
