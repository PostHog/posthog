import json
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.test.utils import override_settings
from django.utils import timezone
from freezegun import freeze_time

from posthog.ee import is_ee_enabled
from posthog.models.dashboard_item import DashboardItem
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import TransactionBaseTest

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
                        "date_from": "-90d",
                    },
                },
                content_type="application/json",
            ).json()

            response = DashboardItem.objects.all()
            self.assertEqual(len(response), 1)
            self.assertEqual(response[0].filters["events"][0]["id"], "$pageview")
            self.assertEqual(response[0].filters["date_from"], "-90d")

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
        if not is_ee_enabled():

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

    return TestInsightApi


class TestInsightApi(insight_test_factory(Event.objects.create, Person.objects.create)):  # type: ignore
    pass
