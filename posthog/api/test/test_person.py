import json
from typing import Dict, List, Optional, cast
from unittest import mock

from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status

from posthog.client import sync_execute
from posthog.models import Cohort, Organization, Person, Team
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import PersonDistinctId
from posthog.models.person.util import create_person
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    test_with_materialized_columns,
)


class TestPerson(ClickhouseTestMixin, APIBaseTest):
    def test_search(self) -> None:
        _create_person(team=self.team, distinct_ids=["distinct_id"], properties={"email": "someone@gmail.com"})
        _create_person(
            team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com", "name": "james"}
        )
        _create_person(team=self.team, distinct_ids=["distinct_id_3"], properties={"name": "jane"})

        flush_persons_and_events()
        response = self.client.get("/api/person/?search=another@gm")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        response = self.client.get("/api/person/?search=distinct_id_3")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_properties(self) -> None:
        _create_person(team=self.team, distinct_ids=["distinct_id"], properties={"email": "someone@gmail.com"})
        _create_person(team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com"})
        _create_person(team=self.team, distinct_ids=["distinct_id_3"], properties={})
        flush_persons_and_events()

        response = self.client.get(
            "/api/person/?properties=%s"
            % json.dumps([{"key": "email", "operator": "is_set", "value": "is_set", "type": "person"}])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

        response = self.client.get(
            "/api/person/?properties=%s"
            % json.dumps([{"key": "email", "operator": "icontains", "value": "another@gm", "type": "person"}])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_person_property_names(self) -> None:
        _create_person(
            distinct_ids=["person_1"], team=self.team, properties={"$browser": "whatever", "$os": "Mac OS X"}
        )
        _create_person(distinct_ids=["person_2"], team=self.team, properties={"random_prop": "asdf"})
        _create_person(distinct_ids=["person_3"], team=self.team, properties={"random_prop": "asdf"})
        flush_persons_and_events()

        response = self.client.get("/api/person/properties/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data[0]["name"], "random_prop")
        self.assertEqual(response_data[0]["count"], 2)
        self.assertEqual(response_data[2]["name"], "$os")
        self.assertEqual(response_data[2]["count"], 1)
        self.assertEqual(response_data[1]["name"], "$browser")
        self.assertEqual(response_data[1]["count"], 1)

    @test_with_materialized_columns(person_properties=["random_prop"])
    @snapshot_clickhouse_queries
    def test_person_property_values(self):
        _create_person(
            distinct_ids=["person_1"],
            team=self.team,
            properties={"random_prop": "asdf", "some other prop": "with some text"},
        )
        _create_person(distinct_ids=["person_2"], team=self.team, properties={"random_prop": "asdf"})
        _create_person(distinct_ids=["person_3"], team=self.team, properties={"random_prop": "qwerty"})
        _create_person(distinct_ids=["person_4"], team=self.team, properties={"something_else": "qwerty"})
        flush_persons_and_events()

        response = self.client.get("/api/person/values/?key=random_prop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data[0]["name"], "asdf")
        self.assertEqual(response_data[0]["count"], 2)
        self.assertEqual(response_data[1]["name"], "qwerty")
        self.assertEqual(response_data[1]["count"], 1)
        self.assertEqual(len(response_data), 2)

        response = self.client.get("/api/person/values/?key=random_prop&value=qw")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["name"], "qwerty")
        self.assertEqual(response.json()[0]["count"], 1)

    @test_with_materialized_columns(event_properties=["email"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_filter_person_email(self):

        _create_person(
            team=self.team,
            distinct_ids=["distinct_id", "another_one"],
            properties={"email": "someone@gmail.com"},
            is_identified=True,
            immediate=True,
        )
        person2: Person = _create_person(
            team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com"}, immediate=True
        )
        flush_persons_and_events()

        # Filter
        response = self.client.get("/api/person/?email=another@gmail.com")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person2.uuid))
        self.assertEqual(response.json()["results"][0]["uuid"], str(person2.uuid))

    @snapshot_clickhouse_queries
    def test_filter_person_prop(self):

        _create_person(
            team=self.team,
            distinct_ids=["distinct_id", "another_one"],
            properties={"email": "someone@gmail.com"},
            is_identified=True,
            immediate=True,
        )
        person2: Person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com", "some_prop": "some_value"},
            immediate=True,
        )
        flush_persons_and_events()

        # Filter
        response = self.client.get(
            "/api/person/?properties=%s" % json.dumps([{"key": "some_prop", "value": "some_value", "type": "person"}])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person2.uuid))
        self.assertEqual(response.json()["results"][0]["uuid"], str(person2.uuid))

    def test_filter_person_list(self):

        person1: Person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id", "another_one"],
            properties={"email": "someone@gmail.com"},
            is_identified=True,
            immediate=True,
        )
        person2: Person = _create_person(
            team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com"}, immediate=True
        )
        flush_persons_and_events()

        # Filter by distinct ID
        with self.assertNumQueries(6):
            response = self.client.get("/api/person/?distinct_id=distinct_id")  # must be exact matches
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person1.uuid))

        response = self.client.get("/api/person/?distinct_id=another_one")  # can search on any of the distinct IDs
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person1.uuid))

        # Filter by email
        response = self.client.get("/api/person/?email=another@gmail.com")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person2.uuid))

        # Non-matches return an empty list
        response = self.client.get("/api/person/?email=inexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 0)

        response = self.client.get("/api/person/?distinct_id=inexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 0)

    def test_cant_see_another_organization_pii_with_filters(self):

        # Completely different organization
        another_org: Organization = Organization.objects.create()
        another_team: Team = Team.objects.create(organization=another_org)
        _create_person(team=another_team, distinct_ids=["distinct_id", "x_another_one"])
        _create_person(
            team=another_team, distinct_ids=["x_distinct_id_2"], properties={"email": "team2_another@gmail.com"}
        )

        # Person in current team
        person: Person = _create_person(team=self.team, distinct_ids=["distinct_id"], immediate=True)

        # Filter by distinct ID
        response = self.client.get("/api/person/?distinct_id=distinct_id")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(
            response.json()["results"][0]["id"], str(person.uuid)
        )  # note that even with shared distinct IDs, only the person from the same team is returned

        response = self.client.get("/api/person/?distinct_id=x_another_one")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_person(self):
        person = _create_person(
            team=self.team, distinct_ids=["person_1", "anonymous_id"], properties={"$os": "Chrome"}, immediate=True
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.delete(f"/api/person/{person.uuid}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertEqual(Person.objects.filter(team=self.team).count(), 0)

        response = self.client.delete(f"/api/person/{person.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self._assert_person_activity(
            person_id=None,  # can't query directly for deleted person
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "deleted",
                    "scope": "Person",
                    "item_id": str(person.pk),
                    # don't store deleted person's name, so user primary key
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": str(person.uuid),
                        "short_id": None,
                    },
                    "created_at": "2021-08-25T22:09:14.252000Z",
                }
            ],
        )

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)
        # No async deletion is scheduled
        self.assertEqual(AsyncDeletion.objects.filter(team=self.team).count(), 0)
        ch_events = sync_execute("SELECT count() FROM events WHERE team_id = %(team_id)s", {"team_id": self.team.pk})[
            0
        ][0]
        self.assertEqual(ch_events, 3)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_person_and_events(self):
        person = _create_person(
            team=self.team, distinct_ids=["person_1", "anonymous_id"], properties={"$os": "Chrome"}, immediate=True
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.delete(f"/api/person/{person.uuid}/?delete_events=true")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertEqual(Person.objects.filter(team=self.team).count(), 0)

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)

        # async deletion scheduled and executed
        async_deletion = cast(AsyncDeletion, AsyncDeletion.objects.filter(team=self.team).first())
        self.assertEqual(async_deletion.deletion_type, DeletionType.Person)
        self.assertEqual(async_deletion.key, str(person.uuid))
        self.assertIsNone(async_deletion.delete_verified_at)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_split_people_keep_props(self) -> None:
        # created first
        person1 = _create_person(
            team=self.team, distinct_ids=["1", "2", "3"], properties={"$browser": "whatever", "$os": "Mac OS X"}
        )

        self.client.post("/api/person/%s/split/" % person1.pk, {"main_distinct_id": "1"})

        people = Person.objects.all().order_by("id")
        self.assertEqual(people.count(), 3)
        self.assertEqual(people[0].distinct_ids, ["1"])
        self.assertEqual(people[0].properties, {"$browser": "whatever", "$os": "Mac OS X"})
        self.assertEqual(people[1].distinct_ids, ["2"])
        self.assertEqual(people[2].distinct_ids, ["3"])

        self._assert_person_activity(
            person_id=person1.uuid,
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "split_person",
                    "scope": "Person",
                    "item_id": str(person1.pk),
                    "detail": {
                        "changes": [
                            {
                                "type": "Person",
                                "action": "split",
                                "field": None,
                                "before": None,
                                "after": {"distinct_ids": ["1", "2", "3"]},
                            }
                        ],
                        "name": str(person1.uuid),
                        "trigger": None,
                        "short_id": None,
                    },
                    "created_at": "2021-08-25T22:09:14.252000Z",
                }
            ],
        )

    def test_split_people_delete_props(self) -> None:
        # created first
        person1 = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        response = self.client.post("/api/person/%s/split/" % person1.pk)
        people = Person.objects.all().order_by("id")
        self.assertEqual(people.count(), 3)
        self.assertEqual(people[0].distinct_ids, ["1"])
        self.assertEqual(people[0].properties, {})
        self.assertEqual(people[1].distinct_ids, ["2"])
        self.assertEqual(people[2].distinct_ids, ["3"])
        self.assertTrue(response.json()["success"])

    @mock.patch("posthog.api.person.capture_internal")
    def test_update_person_properties(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        self.client.post(f"/api/person/{person.uuid}/update_property", {"key": "foo", "value": "bar"})

        mock_capture.assert_called_once_with(
            distinct_id="some_distinct_id",
            ip=None,
            site_url=None,
            team_id=self.team.id,
            now=mock.ANY,
            sent_at=None,
            event={
                "event": "$set",
                "properties": {"$set": {"foo": "bar"}},
                "distinct_id": "some_distinct_id",
                "timestamp": mock.ANY,
            },
        )

    @mock.patch("posthog.api.person.capture_internal")
    def test_delete_person_properties(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        self.client.post(f"/api/person/{person.uuid}/delete_property", {"$unset": "foo"})

        mock_capture.assert_called_once_with(
            distinct_id="some_distinct_id",
            ip=None,
            site_url=None,
            team_id=self.team.id,
            now=mock.ANY,
            sent_at=None,
            event={
                "event": "$delete_person_property",
                "distinct_id": "some_distinct_id",
                "properties": {"$unset": ["foo"]},
                "timestamp": mock.ANY,
            },
        )

    def test_return_non_anonymous_name(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id1", "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c"],
        )
        _create_person(
            team=self.team, distinct_ids=["17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c", "distinct_id2"]
        )
        flush_persons_and_events()

        response = self.client.get("/api/person/").json()

        self.assertEqual(response["results"][0]["name"], "distinct_id2")
        self.assertEqual(response["results"][1]["name"], "distinct_id1")

        self.assertEqual(
            response["results"][0]["distinct_ids"],
            ["17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c", "distinct_id2"],
        )
        self.assertEqual(
            response["results"][1]["distinct_ids"],
            ["distinct_id1", "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c"],
        )

    def test_person_cohorts(self) -> None:
        _create_person(team=self.team, distinct_ids=["1"], properties={"$some_prop": "something", "number": 1})
        person2 = _create_person(
            team=self.team, distinct_ids=["2"], properties={"$some_prop": "something", "number": 2}, immediate=True
        )
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort2 = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "number", "value": 1, "type": "person"}]}], name="cohort2"
        )
        cohort3 = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "number", "value": 2, "type": "person"}]}], name="cohort3"
        )
        cohort1.calculate_people_ch(pending_version=0)
        cohort2.calculate_people_ch(pending_version=0)
        cohort3.calculate_people_ch(pending_version=0)

        cohort4 = Cohort.objects.create(
            team=self.team, groups=[], is_static=True, last_calculation=timezone.now(), name="cohort4"
        )
        cohort4.insert_users_by_list(["2"])

        response = self.client.get(f"/api/person/cohorts/?person_id={person2.uuid}").json()
        response["results"].sort(key=lambda cohort: cohort["name"])
        self.assertEqual(len(response["results"]), 3)
        self.assertDictContainsSubset({"id": cohort1.id, "count": 2, "name": cohort1.name}, response["results"][0])
        self.assertDictContainsSubset({"id": cohort3.id, "count": 1, "name": cohort3.name}, response["results"][1])
        self.assertDictContainsSubset({"id": cohort4.id, "count": None, "name": cohort4.name}, response["results"][2])

    def test_split_person_clickhouse(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        response = self.client.post("/api/person/%s/split/" % person.uuid).json()
        self.assertTrue(response["success"])

        people = Person.objects.all().order_by("id")
        clickhouse_people = sync_execute(
            "SELECT id FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertCountEqual(clickhouse_people, [(person.uuid,) for person in people])

        pdis2 = sync_execute(
            "SELECT person_id, distinct_id, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )

        self.assertEqual(len(pdis2), PersonDistinctId.objects.count())

        for person in people:
            self.assertEqual(len(person.distinct_ids), 1)
            matching_row = next(row for row in pdis2 if row[0] == person.uuid)
            self.assertEqual(matching_row, (person.uuid, person.distinct_ids[0], 0))

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_patch_user_property_activity(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        created_person = self.client.get("/api/person/%s/" % person.uuid).json()
        created_person["properties"]["a"] = "b"
        response = self.client.patch("/api/person/%s/" % person.uuid, created_person)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.client.get("/api/person/%s/" % person.uuid)

        self._assert_person_activity(
            person_id=person.uuid,
            expected=[
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email},
                    "activity": "updated",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Person",
                    "item_id": str(person.pk),
                    "detail": {
                        "changes": [
                            {
                                "type": "Person",
                                "action": "changed",
                                "field": "properties",
                                "before": None,
                                "after": None,
                            }
                        ],
                        "trigger": None,
                        "name": None,
                        "short_id": None,
                    },
                }
            ],
        )

    def test_csv_export(self):
        _create_person(
            team=self.team, distinct_ids=["1", "2", "3"], properties={"$browser": "whatever", "$os": "Mac OS X"}
        )
        _create_person(team=self.team, distinct_ids=["4"], properties={"$browser": "whatever", "$os": "Windows"})

        flush_persons_and_events()
        response = self.client.get("/api/person.csv")
        self.assertEqual(len(response.content.splitlines()), 3, response.content)

        response = self.client.get(
            "/api/person.csv?properties=%s" % json.dumps([{"key": "$os", "value": "Windows", "type": "person"}])
        )
        self.assertEqual(len(response.content.splitlines()), 2)

    def test_pagination_limit(self):
        created_ids = []

        for index in range(0, 19):
            created_ids.append(str(index + 100))
            Person.objects.create(  # creating without _create_person to guarentee created_at ordering
                team=self.team, distinct_ids=[str(index + 100)], properties={"$browser": "whatever", "$os": "Windows"}
            )

        # Very occasionally, a person might be deleted in postgres but not in Clickhouse due to network issues or whatever
        # In this case Clickhouse will return a user that then doesn't get returned by postgres.
        # We would return an empty "next" url.
        # Now we just return 9 people instead
        create_person(team_id=self.team.pk, version=0)

        returned_ids = []
        with self.assertNumQueries(6):
            response = self.client.get("/api/person/?limit=10").json()
        self.assertEqual(len(response["results"]), 9)
        returned_ids += [x["distinct_ids"][0] for x in response["results"]]
        response = self.client.get(response["next"]).json()
        returned_ids += [x["distinct_ids"][0] for x in response["results"]]
        self.assertEqual(len(response["results"]), 10)

        created_ids.reverse()  # ids are returned in desc order
        self.assertEqual(returned_ids, created_ids, returned_ids)

    def _get_person_activity(self, person_id: Optional[str] = None, expected_status: int = status.HTTP_200_OK):
        if person_id:
            url = f"/api/person/{person_id}/activity"
        else:
            url = f"/api/person/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def _assert_person_activity(self, person_id: Optional[str], expected: List[Dict]):
        activity_response = self._get_person_activity(person_id)

        activity: List[Dict] = activity_response["results"]
        self.maxDiff = None
        self.assertCountEqual(activity, expected)
