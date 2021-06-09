import json
from datetime import timedelta

from django.test.utils import override_settings
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from posthog.ee import is_clickhouse_enabled
from posthog.models.dashboard_item import DashboardItem
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.test.base import APIBaseTest

# TODO: two tests below fail in EE


def insight_test_factory(event_factory, person_factory):
    class TestInsight(APIBaseTest):
        CLASS_DATA_LEVEL_SETUP = False

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
                filters=Filter(data=filter_dict).to_dict(), saved=True, team=self.team, created_by=self.user,
            )

            # create without saved
            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user,
            )

            # create without user
            DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

            response = self.client.get("/api/insight/", data={"saved": "true", "user": "true"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(len(response.json()["results"][0]["short_id"]), 8)

        def test_get_insight_by_short_id(self):
            filter_dict = {
                "events": [{"id": "$pageview"}],
            }

            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
            )

            # Red herring: Should be ignored because it's not on the current team (even though the user has access)
            new_team = Team.objects.create(organization=self.organization)
            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=new_team, short_id="12345678",
            )

            response = self.client.get("/api/insight/?short_id=12345678")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(response.json()["results"][0]["short_id"], "12345678")
            self.assertEqual(response.json()["results"][0]["filters"]["events"][0]["id"], "$pageview")

        def test_basic_results(self):
            """
            The `skip_results` query parameter can be passed so that only a list of objects is returned, without
            the actual query data. This can speed things up if it's not needed.
            """
            filter_dict = {
                "events": [{"id": "$pageview"}],
            }

            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
            )
            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, saved=True,
            )

            response = self.client.get("/api/insight/?basic=true")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(len(response.json()["results"]), 2)
            self.assertEqual(
                list(response.json()["results"][0].keys()),
                ["id", "short_id", "name", "filters", "dashboard", "color", "last_refresh", "refreshing", "saved"],
            )

        def test_create_insight_items(self):
            # Make sure the endpoint works with and without the trailing slash
            response = self.client.post(
                "/api/insight",
                data={
                    "filters": {
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$browser", "value": "Mac OS X"}],
                        "date_from": "-90d",
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            objects = DashboardItem.objects.all()
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0].filters["events"][0]["id"], "$pageview")
            self.assertEqual(objects[0].filters["date_from"], "-90d")
            self.assertEqual(len(objects[0].short_id), 8)

        # BASIC TESTING OF ENDPOINTS. /queries as in depth testing for each insight

        def test_insight_trends_basic(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="$pageview", distinct_id="2")

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.client.get(
                    "/api/insight/trend/?events={}".format(json.dumps([{"id": "$pageview"}]))
                ).json()

            self.assertEqual(response["result"][0]["count"], 2)
            self.assertEqual(response["result"][0]["action"]["name"], "$pageview")

        def test_insight_trends_breakdown_pagination(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                for i in range(25):

                    event_factory(
                        team=self.team, event="$pageview", distinct_id="1", properties={"$some_property": f"value{i}"},
                    )

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.client.get(
                    "/api/insight/trend/",
                    data={
                        "events": json.dumps([{"id": "$pageview"}]),
                        "breakdown": "$some_property",
                        "breakdown_type": "event",
                    },
                )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("offset=20", response.json()["next"])

        def test_insight_paths_basic(self):
            person_factory(team=self.team, distinct_ids=["person_1"])
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
            )

            response = self.client.get("/api/insight/path",).json()
            self.assertEqual(len(response["result"]), 1)

        # TODO: remove this check
        if not is_clickhouse_enabled():

            @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
            def test_insight_funnels_basic_post(self):
                event_factory(team=self.team, event="user signed up", distinct_id="1")
                response = self.client.post(
                    "/api/insight/funnel/", {"events": [{"id": "user signed up", "type": "events", "order": 0}]}
                ).json()
                self.assertEqual(response["result"]["loading"], True)

            # Tests backwards-compatibility when we changed GET to POST | GET
            @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
            def test_insight_funnels_basic_get(self):
                event_factory(team=self.team, event="user signed up", distinct_id="1")
                response = self.client.get(
                    "/api/insight/funnel/?events={}".format(
                        json.dumps([{"id": "user signed up", "type": "events", "order": 0},])
                    )
                ).json()
                self.assertEqual(response["result"]["loading"], True)

            # TODO: remove this check
            def test_insight_retention_basic(self):
                person_factory(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})
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

                self.assertEqual(len(response["result"]), 11)

    return TestInsight


class TestInsight(insight_test_factory(Event.objects.create, Person.objects.create)):  # type: ignore
    pass
