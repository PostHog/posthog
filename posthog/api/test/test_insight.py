import json
from datetime import datetime, timedelta

from django.test.utils import override_settings
from freezegun.api import freeze_time

from posthog.models.dashboard_item import DashboardItem
from posthog.models.event import Event
from posthog.models.filter import Filter
from posthog.models.person import Person

from .base import TransactionBaseTest


class TestInsightApi(TransactionBaseTest):
    TESTS_API = True

    def test_get_insight_items(self):

        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user)

        # create without user
        DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get("/api/insight/", data={"user": "true"}).json()

        self.assertEqual(len(response["results"]), 1)

    def test_get_saved_insight_items(self):

        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        DashboardItem.objects.create(
            filters=Filter(data=filter_dict).to_dict(), saved=True, team=self.team, created_by=self.user
        )

        # create without saved
        DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user)

        # create without user
        DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get("/api/insight/", data={"saved": "true", "user": "true",},).json()

        self.assertEqual(len(response["results"]), 1)

    def test_create_insight_items(self):

        self.client.post(
            "/api/insight/",
            data={
                "filters": {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},
            },
            content_type="application/json",
        ).json()

        response = DashboardItem.objects.all()
        self.assertEqual(len(response), 1)
        self.assertListEqual(response[0].filters["events"], [{"id": "$pageview"}])

    # BASIC TESTING OF ENDPOINTS. /queries as in depth testing for each insight

    def test_insight_trends_basic(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            Event.objects.create(team=self.team, event="$pageview", distinct_id="1")
            Event.objects.create(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get("/api/insight/trend/?events={}".format(json.dumps([{"id": "$pageview"}]))).json()

        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["action"]["name"], "$pageview")

    def test_insight_session_basic(self):
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
            response = self.client.get("/api/insight/session/",).json()

        self.assertEqual(len(response["result"]), 2)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_insight_funnels_basic(self):
        Event.objects.create(team=self.team, event="user signed up")
        response = self.client.get(
            "/api/insight/funnel/?events={}".format(
                json.dumps([{"id": "user signed up", "type": "events", "order": 0},])
            )
        ).json()
        self.assertEqual(response["loading"], True)

    def test_insight_retention_basic(self):
        person1 = Person.objects.create(
            team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"}
        )
        Event.objects.create(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=datetime.now() - timedelta(days=11)
        )

        Event.objects.create(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=datetime.now() - timedelta(days=10)
        )
        response = self.client.get("/api/insight/retention/",).json()

        self.assertEqual(len(response["data"]), 11)
        self.assertEqual(response["data"][0]["values"][0]["count"], 1)

    def test_insight_paths_basic(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )

        response = self.client.get("/api/insight/path/",).json()
        self.assertEqual(len(response), 1)
