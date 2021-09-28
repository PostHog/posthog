import json
from datetime import timedelta

from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from posthog.models import (
    Cohort,
    Dashboard,
    DashboardItem,
    Event,
    Filter,
    Person,
    Team,
    User,
)
from posthog.test.base import APIBaseTest
from posthog.utils import is_clickhouse_enabled


def insight_test_factory(event_factory, person_factory):
    class TestInsight(APIBaseTest):
        maxDiff = None

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

        def test_get_favorited_insight_items(self):
            filter_dict = {
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "$browser", "value": "Mac OS X"}],
            }

            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), favorited=True, team=self.team, created_by=self.user,
            )

            # create without favorited
            DashboardItem.objects.create(
                filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user,
            )

            # create without user
            DashboardItem.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

            response = self.client.get("/api/insight/?favorited=true&user=true")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual((response.json()["results"][0]["favorited"]), True)

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
                [
                    "id",
                    "short_id",
                    "name",
                    "filters",
                    "dashboard",
                    "color",
                    "description",
                    "last_refresh",
                    "refreshing",
                    "saved",
                    "updated_at",
                ],
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
            self.assertEqual(response.json()["description"], None)
            self.assertEqual(response.json()["tags"], [])

            objects = DashboardItem.objects.all()
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0].filters["events"][0]["id"], "$pageview")
            self.assertEqual(objects[0].filters["date_from"], "-90d")
            self.assertEqual(len(objects[0].short_id), 8)

        def test_update_insight(self):
            insight = DashboardItem.objects.create(team=self.team, name="special insight", created_by=self.user,)
            response = self.client.patch(
                f"/api/insight/{insight.id}",
                {
                    "name": "insight new name",
                    "tags": ["official", "engineering"],
                    "description": "Internal system metrics.",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], "insight new name")
            self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
            self.assertEqual(response_data["description"], "Internal system metrics.")
            self.assertEqual(response_data["tags"], ["official", "engineering"])

            insight.refresh_from_db()
            self.assertEqual(insight.name, "insight new name")
            self.assertEqual(insight.tags, ["official", "engineering"])

        def test_update_insight_filters(self):
            insight = DashboardItem.objects.create(
                team=self.team,
                name="insight with custom filters",
                created_by=self.user,
                filters={"events": [{"id": "$pageview"}]},
            )

            for custom_name, expected_name in zip(
                ["Custom filter", 100, "", "  ", None], ["Custom filter", "100", None, None, None]
            ):
                response = self.client.patch(
                    f"/api/insight/{insight.id}",
                    {"filters": {"events": [{"id": "$pageview", "custom_name": custom_name}]}},
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)

                response_data = response.json()
                self.assertEqual(response_data["filters"]["events"][0]["custom_name"], expected_name)
                insight.refresh_from_db()
                self.assertEqual(insight.filters["events"][0]["custom_name"], expected_name)

        def test_save_new_funnel(self):

            dashboard = Dashboard.objects.create(name="My Dashboard", team=self.team)

            response = self.client.post(
                "/api/insight",
                data={
                    "filters": {
                        "insight": "FUNNELS",
                        "events": [
                            {
                                "id": "$pageview",
                                "math": None,
                                "name": "$pageview",
                                "type": "events",
                                "order": 0,
                                "properties": [],
                                "math_property": None,
                            },
                            {
                                "id": "$rageclick",
                                "math": None,
                                "name": "$rageclick",
                                "type": "events",
                                "order": 2,
                                "properties": [],
                                "math_property": None,
                            },
                        ],
                        "display": "FunnelViz",
                        "interval": "day",
                        "date_from": "-30d",
                        "actions": [],
                        "new_entity": [],
                        "layout": "horizontal",
                    },
                    "name": "My Funnel One",
                    "dashboard": dashboard.pk,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            objects = DashboardItem.objects.all()
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0].filters["events"][1]["id"], "$rageclick")
            self.assertEqual(objects[0].filters["display"], "FunnelViz")
            self.assertEqual(objects[0].filters["interval"], "day")
            self.assertEqual(objects[0].filters["date_from"], "-30d")
            self.assertEqual(objects[0].filters["layout"], "horizontal")
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

        def test_nonexistent_cohort_is_handled(self):
            response_nonexistent_property = self.client.get(
                f"/api/insight/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'event','key':'foo','value':'barabarab'}])}"
            )
            response_nonexistent_cohort = self.client.get(
                f"/api/insight/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':2137}])}"
            )  # This should not throw an error, just act like there's no event matches

            response_nonexistent_property_data = response_nonexistent_property.json()
            response_nonexistent_cohort_data = response_nonexistent_cohort.json()
            response_nonexistent_property_data.pop("last_refresh")
            response_nonexistent_cohort_data.pop("last_refresh")
            self.assertEqual(
                response_nonexistent_property_data, response_nonexistent_cohort_data
            )  # Both cases just empty

        def test_cohort_without_match_group_works(self):
            whatever_cohort_without_match_groups = Cohort.objects.create(team=self.team)

            response_nonexistent_property = self.client.get(
                f"/api/insight/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'event','key':'foo','value':'barabarab'}])}"
            )
            response_cohort_without_match_groups = self.client.get(
                f"/api/insight/trend/?events={json.dumps([{'id':'$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':whatever_cohort_without_match_groups.pk}])}"
            )  # This should not throw an error, just act like there's no event matches

            self.assertEqual(response_nonexistent_property.status_code, 200)
            response_nonexistent_property_data = response_nonexistent_property.json()
            response_cohort_without_match_groups_data = response_cohort_without_match_groups.json()
            response_nonexistent_property_data.pop("last_refresh")
            response_cohort_without_match_groups_data.pop("last_refresh")
            self.assertEqual(
                response_nonexistent_property_data, response_cohort_without_match_groups_data
            )  # Both cases just empty

        def test_precalculated_cohort_works(self):
            person_factory(team=self.team, distinct_ids=["person_1"], properties={"foo": "bar"})

            whatever_cohort: Cohort = Cohort.objects.create(
                id=113,
                team=self.team,
                groups=[{"properties": [{"type": "person", "key": "foo", "value": "bar", "operator": "exact"}]}],
                last_calculation=timezone.now(),
            )
            whatever_cohort.calculate_people()
            whatever_cohort.calculate_people_ch()

            with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
                response_user_property = self.client.get(
                    f"/api/insight/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'person','key':'foo','value':'bar'}])}"
                )
                response_precalculated_cohort = self.client.get(
                    f"/api/insight/trend/?events={json.dumps([{'id':'$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':113}])}"
                )

            self.assertEqual(response_precalculated_cohort.status_code, 200)
            response_user_property_data = response_user_property.json()
            response_precalculated_cohort_data = response_precalculated_cohort.json()
            response_user_property_data.pop("last_refresh")
            response_precalculated_cohort_data.pop("last_refresh")
            self.assertEqual(response_user_property_data, response_precalculated_cohort_data)

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

        def test_insight_funnels_basic_post(self):
            person_factory(team=self.team, distinct_ids=["1"])
            event_factory(team=self.team, event="user signed up", distinct_id="1")
            event_factory(team=self.team, event="user did things", distinct_id="1")
            response = self.client.post(
                "/api/insight/funnel/",
                {
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {"id": "user did things", "type": "events", "order": 1},
                    ],
                    "funnel_window_days": 14,
                },
            ).json()

            # clickhouse funnels don't have a loading system
            if is_clickhouse_enabled():
                self.assertEqual(len(response["result"]), 2)
                self.assertEqual(response["result"][0]["name"], "user signed up")
                self.assertEqual(response["result"][0]["count"], 1)
                self.assertEqual(response["result"][1]["name"], "user did things")
                self.assertEqual(response["result"][1]["count"], 1)
            else:
                self.assertEqual(response["result"]["loading"], True)

        # Tests backwards-compatibility when we changed GET to POST | GET
        def test_insight_funnels_basic_get(self):
            event_factory(team=self.team, event="user signed up", distinct_id="1")
            event_factory(team=self.team, event="user did things", distinct_id="1")
            response = self.client.get(
                "/api/insight/funnel/?funnel_window_days=14&events={}".format(
                    json.dumps(
                        [
                            {"id": "user signed up", "type": "events", "order": 0},
                            {"id": "user did things", "type": "events", "order": 1},
                        ]
                    )
                )
            ).json()

            # clickhouse funnels don't have a loading system
            if is_clickhouse_enabled():
                self.assertEqual(len(response["result"]), 2)
                self.assertEqual(response["result"][0]["name"], "user signed up")
                self.assertEqual(response["result"][1]["name"], "user did things")
            else:
                self.assertEqual(response["result"]["loading"], True)

        def test_insight_retention_basic(self):
            person_factory(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=11),
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=10),
            )
            response = self.client.get("/api/insight/retention/",).json()

            self.assertEqual(len(response["result"]), 11)

        def test_insight_with_specified_token(self):
            _, _, user = User.objects.bootstrap("Test", "team2@posthog.com", None)
            assert user.team is not None
            assert self.team is not None
            assert self.user.team is not None

            self.assertNotEqual(user.team.id, self.team.id)
            self.client.force_login(self.user)

            person_factory(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})

            event_factory(
                team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=6),
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=5),
            )

            events_filter = json.dumps([{"id": "$pageview"}])
            response_team1 = self.client.get(f"/api/insight/trend/?events={events_filter}")
            response_team1_token = self.client.get(
                f"/api/insight/trend/?events={events_filter}&token={self.user.team.api_token}"
            )
            response_team2 = self.client.get(
                f"/api/insight/trend/?events={events_filter}", data={"token": user.team.api_token}
            )

            self.assertEqual(response_team1.json()["result"], response_team1_token.json()["result"])
            self.assertNotEqual(len(response_team1.json()["result"]), len(response_team2.json()["result"]))

            response_invalid_token = self.client.get(f"/api/insight/trend?token=invalid")
            self.assertEqual(response_invalid_token.status_code, 401)

    return TestInsight


class TestInsight(insight_test_factory(Event.objects.create, Person.objects.create)):  # type: ignore
    pass
