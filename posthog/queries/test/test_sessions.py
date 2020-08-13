from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Event, Filter
from posthog.queries.sessions import Sessions


class TestSessions(BaseTest):
    def test_sessions_list(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            Event.objects.create(team=self.team, event="1st action", distinct_id="1")
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
        with freeze_time("2012-01-14T03:25:34.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="1")
            Event.objects.create(team=self.team, event="2nd action", distinct_id="2")
        with freeze_time("2012-01-15T03:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-15T03:59:35.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="1")
        with freeze_time("2012-01-15T04:01:34.000Z"):
            Event.objects.create(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
            Event.objects.create(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = Sessions().run(Filter(data={"events": [], "session": None}), self.team)
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["global_session_id"], 1)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = Sessions().run(
                Filter(data={"events": [], "properties": [{"key": "$os", "value": "Mac OS X"}], "session": None}),
                self.team,
            )
        self.assertEqual(len(response), 1)

    def test_sessions_avg_length(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            Event.objects.create(team=self.team, event="1st action", distinct_id="1")
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
        with freeze_time("2012-01-14T03:25:34.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="1")
            Event.objects.create(team=self.team, event="2nd action", distinct_id="2")
        with freeze_time("2012-01-15T03:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="1")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-15T04:01:34.000Z"):
            Event.objects.create(team=self.team, event="4th action", distinct_id="1")
            Event.objects.create(team=self.team, event="4th action", distinct_id="2")

        response = Sessions().run(Filter(data={"date_from": "all", "session": "avg"}), self.team)
        self.assertEqual(response[0]["count"], 3)  # average length of all sessions

        # time series
        self.assertEqual(response[0]["data"][0], 240)
        self.assertEqual(response[0]["data"][1], 120)
        self.assertEqual(response[0]["labels"][0], "Sat. 14 January")
        self.assertEqual(response[0]["labels"][1], "Sun. 15 January")
        self.assertEqual(response[0]["days"][0], "2012-01-14")
        self.assertEqual(response[0]["days"][1], "2012-01-15")

    def test_sessions_avg_length_interval(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            Event.objects.create(team=self.team, event="1st action", distinct_id="1")
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
        with freeze_time("2012-01-14T03:25:34.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="1")
            Event.objects.create(team=self.team, event="2nd action", distinct_id="2")
        with freeze_time("2012-01-25T03:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="1")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-25T04:01:34.000Z"):
            Event.objects.create(team=self.team, event="4th action", distinct_id="1")
            Event.objects.create(team=self.team, event="4th action", distinct_id="2")

        with freeze_time("2012-03-14T03:21:34.000Z"):
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
        with freeze_time("2012-03-14T03:25:34.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="2")
        with freeze_time("2012-03-15T03:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-03-15T04:01:34.000Z"):
            Event.objects.create(team=self.team, event="4th action", distinct_id="2")

        # month
        month_response = Sessions().run(
            Filter(data={"date_from": "2012-01-01", "date_to": "2012-04-01", "interval": "month", "session": "avg"}),
            self.team,
        )
        self.assertEqual(month_response[0]["data"][0], 180)
        self.assertEqual(month_response[0]["data"][2], 180)
        self.assertEqual(month_response[0]["labels"][0], "Tue. 31 January")
        self.assertEqual(month_response[0]["labels"][1], "Wed. 29 February")
        self.assertEqual(month_response[0]["days"][0], "2012-01-31")
        self.assertEqual(month_response[0]["days"][1], "2012-02-29")

        # # week
        week_response = Sessions().run(
            Filter(data={"date_from": "2012-01-01", "date_to": "2012-02-01", "interval": "week", "session": "avg"}),
            self.team,
        )
        self.assertEqual(week_response[0]["data"][1], 240.0)
        self.assertEqual(week_response[0]["data"][3], 120.0)
        self.assertEqual(week_response[0]["labels"][0], "Sun. 1 January")
        self.assertEqual(week_response[0]["labels"][1], "Sun. 8 January")
        self.assertEqual(week_response[0]["days"][0], "2012-01-01")
        self.assertEqual(week_response[0]["days"][1], "2012-01-08")

        # # # hour
        hour_response = Sessions().run(
            Filter(data={"date_from": "2012-03-14", "date_to": "2012-03-16", "interval": "hour", "session": "avg"}),
            self.team,
        )
        self.assertEqual(hour_response[0]["data"][3], 240.0)
        self.assertEqual(hour_response[0]["data"][27], 120.0)
        self.assertEqual(hour_response[0]["labels"][0], "Wed. 14 March, 00:00")
        self.assertEqual(hour_response[0]["labels"][1], "Wed. 14 March, 01:00")
        self.assertEqual(hour_response[0]["days"][0], "2012-03-14 00:00:00")
        self.assertEqual(hour_response[0]["days"][1], "2012-03-14 01:00:00")

    def test_no_events(self):
        response = Sessions().run(
            Filter(data={"date_from": "2012-01-20", "date_to": "2012-01-30", "interval": "day", "session": "avg"}),
            self.team,
        )
        self.assertEqual(response, [])

    def test_compare(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            Event.objects.create(team=self.team, event="1st action", distinct_id="1")
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
        with freeze_time("2012-01-14T03:25:34.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="1")
            Event.objects.create(team=self.team, event="2nd action", distinct_id="2")
        with freeze_time("2012-01-25T03:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="1")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-25T04:01:34.000Z"):
            Event.objects.create(team=self.team, event="4th action", distinct_id="1")
            Event.objects.create(team=self.team, event="4th action", distinct_id="2")
        filter = Filter(
            data={
                "date_from": "2012-01-20",
                "date_to": "2012-01-30",
                "interval": "day",
                "compare": True,
                "session": "avg",
            }
        )
        # Run without anything to compare to
        compare_response = Sessions().run(filter=filter, team=self.team)
        self.assertEqual(compare_response[0]["data"][5], 120.0)
        self.assertEqual(compare_response[1]["data"][4], 240.0)

    def test_sessions_count_buckets(self):

        # 0 seconds
        with freeze_time("2012-01-11T01:25:30.000Z"):
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
            Event.objects.create(team=self.team, event="1st action", distinct_id="2")
            Event.objects.create(team=self.team, event="1st action", distinct_id="4")
        with freeze_time("2012-01-11T01:25:32.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="4")  # within 0-3 seconds
            Event.objects.create(team=self.team, event="1st action", distinct_id="6")
            Event.objects.create(team=self.team, event="2nd action", distinct_id="7")
        with freeze_time("2012-01-11T01:25:40.000Z"):
            Event.objects.create(team=self.team, event="2nd action", distinct_id="6")  # within 3-10 seconds
            Event.objects.create(team=self.team, event="2nd action", distinct_id="7")  # within 3-10 seconds

        with freeze_time("2012-01-15T04:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="4")
        with freeze_time("2012-01-15T05:00:00.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")  # within 10-30 seconds
        with freeze_time("2012-01-15T05:00:20.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="4")  # within 30-60 seconds

        # within 1-3 mins
        with freeze_time("2012-01-17T04:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="1")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="5")
        with freeze_time("2012-01-17T05:01:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="1")
        with freeze_time("2012-01-17T05:07:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")  # test many events within a range
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")  # within 3-10 mins
            Event.objects.create(team=self.team, event="3rd action", distinct_id="10")

        with freeze_time("2012-01-17T05:20:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="5")  # within 10-30 mins
            Event.objects.create(team=self.team, event="3rd action", distinct_id="9")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="10")
        with freeze_time("2012-01-17T05:40:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="9")
            Event.objects.create(team=self.team, event="3rd action", distinct_id="10")  # within 30-60 mins
        with freeze_time("2012-01-17T05:58:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="9")  # -> within 30-60 mins

        # within 1+ hours
        with freeze_time("2012-01-21T04:59:34.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-21T05:20:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-21T05:45:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-21T06:00:30.000Z"):
            Event.objects.create(team=self.team, event="3rd action", distinct_id="2")

        response = Sessions().run(Filter(data={"date_from": "all", "session": "dist"}), self.team)
        compared_response = Sessions().run(
            Filter(data={"date_from": "all", "compare": True, "session": "dist"}), self.team
        )
        for index, item in enumerate(response):
            if item["label"] == "30-60 minutes" or item["label"] == "3-10 seconds":
                self.assertEqual(item["count"], 2)
                self.assertEqual(compared_response[index]["count"], 2)
            else:
                self.assertEqual(item["count"], 1)
                self.assertEqual(compared_response[index]["count"], 1)
