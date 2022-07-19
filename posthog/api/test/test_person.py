import json
import unittest
from datetime import datetime
from typing import Dict, List, Optional
from unittest import mock

from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status

from posthog.api.person import PersonSerializer
from posthog.client import sync_execute
from posthog.models import Cohort, Organization, Person, Team
from posthog.models.person import PersonDistinctId
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
        _create_person(
            team=self.team, distinct_ids=["distinct_id"], properties={"email": "someone@gmail.com"},
        )
        _create_person(
            team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com", "name": "james"},
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
        _create_person(
            team=self.team, distinct_ids=["distinct_id"], properties={"email": "someone@gmail.com"},
        )
        _create_person(
            team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com"},
        )
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
        _create_person(
            team=another_team, distinct_ids=["distinct_id", "x_another_one"],
        )
        _create_person(
            team=another_team, distinct_ids=["x_distinct_id_2"], properties={"email": "team2_another@gmail.com"},
        )

        # Person in current team
        person: Person = _create_person(team=self.team, distinct_ids=["distinct_id"], immediate=True)

        # Filter by distinct ID
        response = self.client.get("/api/person/?distinct_id=distinct_id")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(
            response.json()["results"][0]["id"], str(person.uuid),
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
                    "detail": {"changes": None, "merge": None, "name": str(person.pk), "short_id": None},
                    "created_at": "2021-08-25T22:09:14.252000Z",
                }
            ],
        )

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)

    @freeze_time("2021-08-25T22:09:14.252Z")
    @mock.patch("posthog.api.capture.capture_internal")
    def test_merge_people(self, mock_capture_internal) -> None:

        # created first
        person3 = _create_person(team=self.team, distinct_ids=["distinct_id_3"], properties={"oh": "hello"})
        person1 = _create_person(
            team=self.team, distinct_ids=["1"], properties={"$browser": "whatever", "$os": "Mac OS X"}
        )
        person2 = _create_person(team=self.team, distinct_ids=["2"], properties={"random_prop": "asdf"})

        response = self.client.post("/api/person/%s/merge/" % person1.pk, {"ids": [person2.pk, person3.pk]},)
        mock_capture_internal.assert_has_calls(
            [
                mock.call(
                    {"event": "$create_alias", "properties": {"alias": "2"}},
                    "1",
                    None,
                    None,
                    unittest.mock.ANY,
                    unittest.mock.ANY,
                    self.team.id,
                ),
                mock.call(
                    {"event": "$create_alias", "properties": {"alias": "distinct_id_3"}},
                    "1",
                    None,
                    None,
                    unittest.mock.ANY,
                    unittest.mock.ANY,
                    self.team.id,
                ),
            ],
            any_order=True,
        )
        self.assertEqual(response.status_code, 201)
        self.assertCountEqual(response.json()["distinct_ids"], ["1", "2", "distinct_id_3"])

        person_one_dict = PersonSerializer(person1).data
        person_two_dict = PersonSerializer(person2).data
        person_three_dict = PersonSerializer(person3).data

        person_three_log = {
            "user": {"first_name": "", "email": "user1@posthog.com"},
            "activity": "was_merged_into_person",
            "scope": "Person",
            "item_id": str(person3.pk),
            "detail": {
                "changes": None,
                "name": None,
                "merge": {"type": "Person", "source": person_three_dict, "target": person_one_dict},
                "short_id": None,
            },
            "created_at": "2021-08-25T22:09:14.252000Z",
        }
        person_one_log = {
            "user": {"first_name": "", "email": "user1@posthog.com"},
            "activity": "people_merged_into",
            "scope": "Person",
            # don't store deleted person's name, so user primary key
            "item_id": str(person1.pk),
            "detail": {
                "changes": None,
                "name": None,
                "merge": {"type": "Person", "source": [person_three_dict, person_two_dict], "target": person_one_dict},
                "short_id": None,
            },
            "created_at": "2021-08-25T22:09:14.252000Z",
        }
        person_two_log = {
            "user": {"first_name": "", "email": "user1@posthog.com"},
            "activity": "was_merged_into_person",
            "scope": "Person",
            "item_id": str(person2.pk),
            "detail": {
                "changes": None,
                "name": None,
                "merge": {"type": "Person", "source": person_two_dict, "target": person_one_dict},
                "short_id": None,
            },
            "created_at": "2021-08-25T22:09:14.252000Z",
        }

        self._assert_person_activity(
            person_id=None,  # changes for all three people
            expected=[person_three_log, person_one_log, person_two_log,],
        )
        self._assert_person_activity(
            person_id=person1.pk, expected=[person_one_log,],
        )
        self._assert_person_activity(
            person_id=person2.pk, expected=[person_two_log,],
        )
        self._assert_person_activity(
            person_id=person3.pk, expected=[person_three_log,],
        )

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_split_people_keep_props(self) -> None:
        # created first
        person1 = _create_person(
            team=self.team, distinct_ids=["1", "2", "3"], properties={"$browser": "whatever", "$os": "Mac OS X"}
        )

        self.client.post(
            "/api/person/%s/split/" % person1.pk, {"main_distinct_id": "1"},
        )

        people = Person.objects.all().order_by("id")
        self.assertEqual(people.count(), 3)
        self.assertEqual(people[0].distinct_ids, ["1"])
        self.assertEqual(people[0].properties, {"$browser": "whatever", "$os": "Mac OS X"})
        self.assertEqual(people[1].distinct_ids, ["2"])
        self.assertEqual(people[2].distinct_ids, ["3"])

        self._assert_person_activity(
            person_id=person1.pk,
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
                        "name": None,
                        "merge": None,
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

        response = self.client.post("/api/person/%s/split/" % person1.pk,)
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

        self.client.patch(f"/api/person/{person.uuid}", {"properties": {"foo": "bar"}})

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
            team=self.team, distinct_ids=["17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c", "distinct_id2"],
        )
        flush_persons_and_events()

        response = self.client.get("/api/person/").json()

        self.assertEqual(response["results"][0]["name"], "distinct_id1")
        self.assertEqual(response["results"][1]["name"], "distinct_id2")

        self.assertEqual(
            response["results"][0]["distinct_ids"],
            ["distinct_id1", "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c"],
        )
        self.assertEqual(
            response["results"][1]["distinct_ids"],
            ["17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c", "distinct_id2"],
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

        response = self.client.get(f"/api/person/cohorts/?person_id={person2.id}").json()
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

        response = self.client.post("/api/person/%s/split/" % person.uuid,).json()
        self.assertTrue(response["success"])

        people = Person.objects.all().order_by("id")
        clickhouse_people = sync_execute(
            "SELECT id FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertCountEqual(clickhouse_people, [(person.uuid,) for person in people])

        distinct_id_rows = PersonDistinctId.objects.all().order_by("person_id")
        pdis = sync_execute(
            "SELECT person_id, distinct_id FROM person_distinct_id FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        self.assertCountEqual(pdis, [(pdi.person.uuid, pdi.distinct_id) for pdi in distinct_id_rows])

        pdis2 = sync_execute(
            "SELECT person_id, distinct_id FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        self.assertCountEqual(pdis2, [(pdi.person.uuid, pdi.distinct_id) for pdi in distinct_id_rows])

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
            person_id=person.pk,
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
                        "merge": None,
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
        for index in range(0, 20):
            created_ids.append(str(index + 100))
            _create_person(
                team=self.team, distinct_ids=[str(index + 100)], properties={"$browser": "whatever", "$os": "Windows"},
            )

        with freeze_time(datetime(2022, 1, 1, 0, 0)):
            flush_persons_and_events()
        returned_ids = []
        response = self.client.get("/api/person/?limit=10").json()
        self.assertEqual(len(response["results"]), 10)
        returned_ids += [x["distinct_ids"][0] for x in response["results"]]
        response = self.client.get(response["next"]).json()
        returned_ids += [x["distinct_ids"][0] for x in response["results"]]

        self.assertCountEqual(returned_ids, created_ids, returned_ids)

    def _get_person_activity(self, person_id: Optional[int] = None, expected_status: int = status.HTTP_200_OK):
        if person_id:
            url = f"/api/person/{person_id}/activity"
        else:
            url = f"/api/person/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def _assert_person_activity(self, person_id: Optional[int], expected: List[Dict]):
        activity_response = self._get_person_activity(person_id)

        activity: List[Dict] = activity_response["results"]
        self.maxDiff = None
        self.assertCountEqual(
            activity, expected,
        )
