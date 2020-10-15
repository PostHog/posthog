import json
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.test.utils import override_settings
from django.utils import timezone
from freezegun import freeze_time

from posthog.ee import check_ee_enabled
from posthog.models.dashboard_item import DashboardItem
from posthog.models.event import Event
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.utils import relative_date_parse

from .base import TransactionBaseTest

# TODO: two tests below fail in EE


def insight_test_factory(event_factory, person_factory):
    class TestInsightApi(TransactionBaseTest):
        TESTS_API = True

        def test_get_insight_items(self):
            filter_dict = {
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "$browser", "value": "Mac OS X"}],
            }

            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user
            )

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
            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user
            )

            # create without user
            DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

            response = self.client.get("/api/insight/", data={"saved": "true", "user": "true",},).json()

            self.assertEqual(len(response["results"]), 1)

        def test_create_insight_items(self):
            # Make sure the endpoint works with and without the trailing slash
            self.client.post(
                "/api/insight",
                data={
                    "filters": {
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$browser", "value": "Mac OS X"}],
                    },
                },
                content_type="application/json",
            ).json()

            response = DashboardItem.objects.all()
            self.assertEqual(len(response), 1)
            self.assertListEqual(response[0].filters["events"], [{"id": "$pageview"}])

        # BASIC TESTING OF ENDPOINTS. /queries as in depth testing for each insight

        def test_insight_trends_basic(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="$pageview", distinct_id="2")

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.client.get(
                    "/api/insight/trend/?events={}".format(json.dumps([{"id": "$pageview"}]))
                ).json()

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["action"]["name"], "$pageview")

        def test_insight_session_basic(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.client.get("/api/insight/session/",).json()

            self.assertEqual(len(response["result"]), 2)

            response = self.client.get("/api/insight/session/?date_from=2012-01-14&date_to=2012-01-15",).json()
            self.assertEqual(len(response["result"]), 4)

            for i in range(46):
                with freeze_time(relative_date_parse("2012-01-15T04:01:34.000Z") + relativedelta(hours=i)):
                    event_factory(team=self.team, event="action {}".format(i), distinct_id=str(i + 3))

            response = self.client.get("/api/insight/session/?date_from=2012-01-14&date_to=2012-01-17",).json()
            self.assertEqual(len(response["result"]), 50)
            self.assertEqual(response.get("offset", None), None)

            for i in range(2):
                with freeze_time(relative_date_parse("2012-01-15T04:01:34.000Z") + relativedelta(hours=i + 46)):
                    event_factory(team=self.team, event="action {}".format(i), distinct_id=str(i + 49))

            response = self.client.get("/api/insight/session/?date_from=2012-01-14&date_to=2012-01-17",).json()
            self.assertEqual(len(response["result"]), 50)
            self.assertEqual(response["offset"], 50)

            response = self.client.get(
                "/api/insight/session/?date_from=2012-01-14&date_to=2012-01-17&offset=50",
            ).json()
            self.assertEqual(len(response["result"]), 2)
            self.assertEqual(response.get("offset", None), None)

        def test_insight_paths_basic(self):
            person1 = person_factory(team=self.team, distinct_ids=["person_1"])
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
            )

            response = self.client.get("/api/insight/path",).json()
            self.assertEqual(len(response), 1)

        # TODO: remove this check
        if not check_ee_enabled():

            @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
            def test_insight_funnels_basic(self):
                event_factory(team=self.team, event="user signed up", distinct_id="1")
                response = self.client.get(
                    "/api/insight/funnel/?events={}".format(
                        json.dumps([{"id": "user signed up", "type": "events", "order": 0},])
                    )
                ).json()
                self.assertEqual(response["loading"], True)

            # TODO: remove this check
            def test_insight_retention_basic(self):
                person1 = person_factory(
                    team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"}
                )
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="person1",
                    timestamp=timezone.now() - timedelta(days=11),
                )

                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="person1",
                    timestamp=timezone.now() - timedelta(days=10),
                )
                response = self.client.get("/api/insight/retention/",).json()

                self.assertEqual(len(response["data"]), 11)

            def test_insight_session_by_id(self):
                Person.objects.create(team=self.team, distinct_ids=["1"])
                with freeze_time("2012-01-14T03:21:34.000Z"):
                    event_factory(team=self.team, event="1st action", distinct_id="1")
                    event_factory(team=self.team, event="1st action", distinct_id="2")
                with freeze_time("2012-01-14T03:25:34.000Z"):
                    event_factory(team=self.team, event="2nd action", distinct_id="1")
                    event_factory(team=self.team, event="2nd action", distinct_id="2")
                with freeze_time("2012-01-15T03:59:35.000Z"):
                    event_factory(team=self.team, event="3rd action", distinct_id="1")
                with freeze_time("2012-01-15T04:01:34.000Z"):
                    event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
                    event_factory(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

                with freeze_time("2012-01-15T04:01:34.000Z"):
                    response_person_1 = self.client.get("/api/insight/session/?distinct_id=1",).json()

                self.assertEqual(len(response_person_1["result"]), 1)

    return TestInsightApi


class TestInsightApi(insight_test_factory(Event.objects.create, Person.objects.create)):  # type: ignore
    pass
