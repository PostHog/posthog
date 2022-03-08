import json
from datetime import timedelta
from unittest.case import skip
from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.models import Cohort, Dashboard, Filter, Insight, Person, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.tasks.update_cache import update_dashboard_item_cache
from posthog.test.base import APIBaseTest, QueryMatchingTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=str(person.uuid))


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestInsight(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest, QueryMatchingTest):
    maxDiff = None

    CLASS_DATA_LEVEL_SETUP = False

    def test_get_insight_items(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user)

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/", data={"user": "true"}).json()

        self.assertEqual(len(response["results"]), 1)

    def test_created_updated_and_last_modified(self):
        alt_user = User.objects.create_and_join(self.organization, "team2@posthog.com", None)
        self_user_basic_serialized = {
            "id": self.user.id,
            "uuid": str(self.user.uuid),
            "distinct_id": self.user.distinct_id,
            "first_name": self.user.first_name,
            "email": self.user.email,
        }
        alt_user_basic_serialized = {
            "id": alt_user.id,
            "uuid": str(alt_user.uuid),
            "distinct_id": alt_user.distinct_id,
            "first_name": alt_user.first_name,
            "email": alt_user.email,
        }

        # Newly created insight should have created_at being the current time, and same last_modified_at
        # Fields created_by and last_modified_by should be set to the current user
        with freeze_time("2021-08-23T12:00:00Z"):
            response_1 = self.client.post(f"/api/projects/{self.team.id}/insights/")
            self.assertEqual(response_1.status_code, status.HTTP_201_CREATED)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-08-23T12:00:00Z",
                    "last_modified_at": "2021-08-23T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_1.json(),
            )

        insight_id = response_1.json()["id"]

        # Updating fields that don't change the substance of the insight should affect updated_at
        # BUT NOT last_modified_at or last_modified_by
        with freeze_time("2021-09-20T12:00:00Z"):
            response_2 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"color": "blue", "favorited": True}
            )
            self.assertEqual(response_2.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-09-20T12:00:00Z",
                    "last_modified_at": "2021-08-23T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_2.json(),
            )

        # Updating fields that DO change the substance of the insight should affect updated_at
        # AND last_modified_at plus last_modified_by
        with freeze_time("2021-10-21T12:00:00Z"):
            response_3 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"filters": {"events": []}}
            )
            self.assertEqual(response_3.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-10-21T12:00:00Z",
                    "last_modified_at": "2021-10-21T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_3.json(),
            )
        with freeze_time("2021-12-23T12:00:00Z"):
            response_4 = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}", {"name": "XYZ"})
            self.assertEqual(response_4.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2021-12-23T12:00:00Z",
                    "last_modified_at": "2021-12-23T12:00:00Z",
                    "last_modified_by": self_user_basic_serialized,
                },
                response_4.json(),
            )

        # Field last_modified_by is updated when another user makes a material change
        self.client.force_login(alt_user)
        with freeze_time("2022-01-01T12:00:00Z"):
            response_5 = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"description": "Lorem ipsum."}
            )
            self.assertEqual(response_5.status_code, status.HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "created_at": "2021-08-23T12:00:00Z",
                    "created_by": self_user_basic_serialized,
                    "updated_at": "2022-01-01T12:00:00Z",
                    "last_modified_at": "2022-01-01T12:00:00Z",
                    "last_modified_by": alt_user_basic_serialized,
                },
                response_5.json(),
            )

    def test_get_saved_insight_items(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), saved=True, team=self.team, created_by=self.user,
        )

        # create without saved
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/", data={"saved": "true", "user": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(len(response.json()["results"][0]["short_id"]), 8)

    def test_get_favorited_insight_items(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
            "properties": [{"key": "$browser", "value": "Mac OS X"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), favorited=True, team=self.team, created_by=self.user,
        )

        # create without favorited
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, created_by=self.user,
        )

        # create without user
        Insight.objects.create(filters=Filter(data=filter_dict).to_dict(), team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?favorited=true&user=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual((response.json()["results"][0]["favorited"]), True)

    def test_get_insight_by_short_id(self):
        filter_dict = {
            "events": [{"id": "$pageview"}],
        }

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )

        # Red herring: Should be ignored because it's not on the current team (even though the user has access)
        new_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=new_team, short_id="12345678",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?short_id=12345678")
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

        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, short_id="12345678",
        )
        Insight.objects.create(
            filters=Filter(data=filter_dict).to_dict(), team=self.team, saved=True,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/?basic=true")
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

    def test_insights_does_not_nplus1(self):
        for i in range(20):
            user = User.objects.create(email=f"testuser{i}@posthog.com")
            OrganizationMembership.objects.create(user=user, organization=self.organization)
            dashboard = Dashboard.objects.create(name=f"Dashboard {i}", team=self.team)
            Insight.objects.create(
                filters=Filter(data={"events": [{"id": "$pageview"}]}).to_dict(),
                team=self.team,
                short_id=f"insight{i}",
                dashboard=dashboard,
                created_by=user,
            )

        # 4 for request overhead (django sessions/auth), then item count + items + dashboards + users + organization + tag
        with self.assertNumQueries(12):
            response = self.client.get(f"/api/projects/{self.team.id}/insights")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 20)

    def test_create_insight_items(self):
        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights",
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

        objects = Insight.objects.all()
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].filters["events"][0]["id"], "$pageview")
        self.assertEqual(objects[0].filters["date_from"], "-90d")
        self.assertEqual(len(objects[0].short_id), 8)

    def test_update_insight(self):
        insight = Insight.objects.create(team=self.team, name="special insight", created_by=self.user,)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight.id}",
            {"name": "insight new name", "description": "Internal system metrics.",},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["name"], "insight new name")
        self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["description"], "Internal system metrics.")
        self.assertEqual(
            response_data["effective_restriction_level"], Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )
        self.assertEqual(response_data["effective_privilege_level"], Dashboard.PrivilegeLevel.CAN_EDIT)

        insight.refresh_from_db()
        self.assertEqual(insight.name, "insight new name")

    @skip("Compatibility issue caused by test account filters")
    def test_update_insight_filters(self):
        insight = Insight.objects.create(
            team=self.team,
            name="insight with custom filters",
            created_by=self.user,
            filters={"events": [{"id": "$pageview"}]},
        )

        for custom_name, expected_name in zip(
            ["Custom filter", 100, "", "  ", None], ["Custom filter", "100", None, None, None]
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight.id}",
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
            f"/api/projects/{self.team.id}/insights",
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

        objects = Insight.objects.all()
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].filters["events"][1]["id"], "$rageclick")
        self.assertEqual(objects[0].filters["display"], "FunnelViz")
        self.assertEqual(objects[0].filters["interval"], "day")
        self.assertEqual(objects[0].filters["date_from"], "-30d")
        self.assertEqual(objects[0].filters["layout"], "horizontal")
        self.assertEqual(len(objects[0].short_id), 8)

    @patch("posthog.api.insight.update_dashboard_item_cache", wraps=update_dashboard_item_cache)
    def test_insight_refreshing(self, spy_update_dashboard_item_cache):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights", data={"filters": {"events": [{"id": "$pageview"}]}}
            ).json()
            self.assertEqual(response["last_refresh"], None)

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true").json()
            self.assertEqual(spy_update_dashboard_item_cache.call_count, 1)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 0])
            self.assertEqual(response["last_refresh"], "2012-01-15T04:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")

        with freeze_time("2012-01-15T05:01:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/?refresh=true").json()
            self.assertEqual(spy_update_dashboard_item_cache.call_count, 2)
            self.assertEqual(response["result"][0]["data"], [0, 0, 0, 0, 0, 0, 2, 1])
            self.assertEqual(response["last_refresh"], "2012-01-15T05:01:34Z")
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

        with freeze_time("2012-01-25T05:01:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{response['id']}/").json()
            self.assertEqual(spy_update_dashboard_item_cache.call_count, 2)
            self.assertEqual(response["last_refresh"], None)
            self.assertEqual(response["last_modified_at"], "2012-01-15T04:01:34Z")  # did not change

    # BASIC TESTING OF ENDPOINTS. /queries as in depth testing for each insight

    def test_insight_trends_basic(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
            ).json()

        self.assertEqual(response["result"][0]["count"], 2)
        self.assertEqual(response["result"][0]["action"]["name"], "$pageview")

    def test_nonexistent_cohort_is_handled(self):
        response_nonexistent_property = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'event','key':'foo','value':'barabarab'}])}"
        )
        response_nonexistent_cohort = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':2137}])}"
        )  # This should not throw an error, just act like there's no event matches

        response_nonexistent_property_data = response_nonexistent_property.json()
        response_nonexistent_cohort_data = response_nonexistent_cohort.json()
        response_nonexistent_property_data.pop("last_refresh")
        response_nonexistent_cohort_data.pop("last_refresh")
        self.assertEntityResponseEqual(
            response_nonexistent_property_data["result"], response_nonexistent_cohort_data["result"]
        )  # Both cases just empty

    def test_cohort_without_match_group_works(self):
        whatever_cohort_without_match_groups = Cohort.objects.create(team=self.team)

        response_nonexistent_property = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'event','key':'foo','value':'barabarab'}])}"
        )
        response_cohort_without_match_groups = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id':'$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':whatever_cohort_without_match_groups.pk}])}"
        )  # This should not throw an error, just act like there's no event matches

        self.assertEqual(response_nonexistent_property.status_code, 200)
        response_nonexistent_property_data = response_nonexistent_property.json()
        response_cohort_without_match_groups_data = response_cohort_without_match_groups.json()
        response_nonexistent_property_data.pop("last_refresh")
        response_cohort_without_match_groups_data.pop("last_refresh")
        self.assertEntityResponseEqual(
            response_nonexistent_property_data["result"], response_cohort_without_match_groups_data["result"]
        )  # Both cases just empty

    def test_precalculated_cohort_works(self):
        _create_person(team=self.team, distinct_ids=["person_1"], properties={"foo": "bar"})

        whatever_cohort: Cohort = Cohort.objects.create(
            id=113,
            team=self.team,
            groups=[{"properties": [{"type": "person", "key": "foo", "value": "bar", "operator": "exact"}]}],
            last_calculation=timezone.now(),
        )

        whatever_cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            response_user_property = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties={json.dumps([{'type':'person','key':'foo','value':'bar'}])}"
            )
            response_precalculated_cohort = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id':'$pageview'}])}&properties={json.dumps([{'type':'cohort','key':'id','value':113}])}"
            )

        self.assertEqual(response_precalculated_cohort.status_code, 200)
        response_user_property_data = response_user_property.json()
        response_precalculated_cohort_data = response_precalculated_cohort.json()
        response_user_property_data.pop("last_refresh")
        response_precalculated_cohort_data.pop("last_refresh")

        self.assertEntityResponseEqual(
            response_user_property_data["result"], response_precalculated_cohort_data["result"]
        )

    def test_insight_trends_compare(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):
                _create_event(
                    team=self.team, event="$pageview", distinct_id="1", properties={"$some_property": f"value{i}"},
                )

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={"events": json.dumps([{"id": "$pageview"}]), "compare": "true",},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()
        self.assertEqual(len(result["result"]), 2)
        self.assertEqual(result["result"][0]["compare_label"], "current")
        self.assertEqual(result["result"][1]["compare_label"], "previous")

    def test_insight_trends_breakdown_pagination(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            for i in range(25):

                _create_event(
                    team=self.team, event="$pageview", distinct_id="1", properties={"$some_property": f"value{i}"},
                )

        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(
                f"/api/projects/{self.team.id}/insights/trend/",
                data={
                    "events": json.dumps([{"id": "$pageview"}]),
                    "breakdown": "$some_property",
                    "breakdown_type": "event",
                },
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("offset=25", response.json()["next"])

    def test_insight_paths_basic(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/", "test": "val"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about", "test": "val"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )

        _create_person(team=self.team, distinct_ids=["dontcount"])
        _create_event(
            properties={"$current_url": "/", "test": "val"}, distinct_id="dontcount", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about", "test": "val"},
            distinct_id="dontcount",
            event="$pageview",
            team=self.team,
        )

        get_response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"properties": json.dumps([{"key": "test", "value": "val"}]),},
        ).json()
        post_response = self.client.post(
            f"/api/projects/{self.team.id}/insights/path", {"properties": [{"key": "test", "value": "val"}],}
        ).json()
        self.assertEqual(len(get_response["result"]), 1)
        self.assertEqual(len(post_response["result"]), 1)

    def test_insight_funnels_basic_post(self):
        _create_person(team=self.team, distinct_ids=["1"])
        _create_event(team=self.team, event="user signed up", distinct_id="1")
        _create_event(team=self.team, event="user did things", distinct_id="1")
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user did things", "type": "events", "order": 1},
                ],
                "funnel_window_days": 14,
            },
        ).json()

        # clickhouse funnels don't have a loading system
        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "user signed up")
        self.assertEqual(response["result"][0]["count"], 1)
        self.assertEqual(response["result"][1]["name"], "user did things")
        self.assertEqual(response["result"][1]["count"], 1)

    # Tests backwards-compatibility when we changed GET to POST | GET
    def test_insight_funnels_basic_get(self):
        _create_event(team=self.team, event="user signed up", distinct_id="1")
        _create_event(team=self.team, event="user did things", distinct_id="1")
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/funnel/?funnel_window_days=14&events={json.dumps([{'id': 'user signed up', 'type': 'events', 'order': 0},{'id': 'user did things', 'type': 'events', 'order': 1},])}"
        ).json()

        # clickhouse funnels don't have a loading system
        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "user signed up")
        self.assertEqual(response["result"][1]["name"], "user did things")

    def test_insight_retention_basic(self):
        _create_person(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=11),
        )

        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=10),
        )
        response = self.client.get(f"/api/projects/{self.team.id}/insights/retention/",).json()

        self.assertEqual(len(response["result"]), 11)

    def test_insight_with_specified_token(self):
        _, _, user2 = User.objects.bootstrap("Test", "team2@posthog.com", None)
        assert user2.team is not None
        assert self.team is not None
        assert self.user.team is not None

        self.assertNotEqual(user2.team.id, self.team.id)
        self.client.force_login(self.user)

        _create_person(team=self.team, distinct_ids=["person1"], properties={"email": "person1@test.com"})

        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=6),
        )

        _create_event(
            team=self.team, event="$pageview", distinct_id="person1", timestamp=timezone.now() - timedelta(days=5),
        )

        events_filter = json.dumps([{"id": "$pageview"}])

        response_team1 = self.client.get(f"/api/projects/{self.team.id}/insights/trend/?events={events_filter}")
        response_team1_token = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={events_filter}&token={self.user.team.api_token}"
        )

        self.client.force_login(user2)
        response_team2 = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={events_filter}",
            data={"token": user2.team.api_token},
        )

        self.assertEqual(response_team1.status_code, 200)
        self.assertEqual(response_team2.status_code, 200)
        self.assertEqual(response_team1.json()["result"], response_team1_token.json()["result"])
        self.assertNotEqual(len(response_team1.json()["result"]), len(response_team2.json()["result"]))

        response_invalid_token = self.client.get(f"/api/projects/{self.team.id}/insights/trend?token=invalid")
        self.assertEqual(response_invalid_token.status_code, 401)

    # Extra permissioning tests here
    def test_insight_trends_allowed_if_project_open_and_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = False
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_insight_trends_forbidden_if_project_private_and_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertDictEqual(self.permission_denied_response("You don't have access to the project."), response.json())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_insight_trends_allowed_if_project_private_and_org_member_and_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        self_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.api.insight.capture_exception")
    def test_serializer(self, patch_capture_exception):
        """
        Various regression tests for the serializer
        """
        # Display
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}&properties=%5B%5D&display=ActionsLineGraph"
        )

        self.assertEqual(patch_capture_exception.call_count, 0, patch_capture_exception.call_args_list)

        # Properties with an array
        events = [{"id": "$pageview", "properties": [{"key": "something", "value": ["something"]}]}]
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps(events)}&properties=%5B%5D&display=ActionsLineGraph"
        )
        self.assertEqual(patch_capture_exception.call_count, 0, patch_capture_exception.call_args_list)

        # Breakdown with ints in funnels
        events = [
            {"id": "$pageview", "properties": [{"key": "something", "value": ["something"]}]},
            {"id": "$pageview"},
        ]
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {"events": events, "breakdown": [123, 8124], "breakdown_type": "cohort"},
        )
        # self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_capture_exception.call_count, 0, patch_capture_exception.call_args_list)
