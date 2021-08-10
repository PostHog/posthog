import json
import unittest
from unittest import mock

from rest_framework import status

from posthog.models import Cohort, Event, Organization, Person, Team
from posthog.test.base import APIBaseTest


def factory_test_person(event_factory, person_factory, get_events, get_people):
    class TestPerson(APIBaseTest):
        def test_search(self) -> None:
            person_factory(
                team=self.team, distinct_ids=["distinct_id"], properties={"email": "someone@gmail.com"},
            )
            person_factory(
                team=self.team,
                distinct_ids=["distinct_id_2"],
                properties={"email": "another@gmail.com", "name": "james"},
            )
            person_factory(team=self.team, distinct_ids=["distinct_id_3"], properties={"name": "jane"})

            response = self.client.get("/api/person/?search=has:email")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 2)

            response = self.client.get("/api/person/?search=another@gm")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)

            response = self.client.get("/api/person/?search=another@gm%20has:invalid_property")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 0)

            response = self.client.get("/api/person/?search=another@gm%20has:name")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)

            response = self.client.get("/api/person/?search=_id_3")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)

        def test_properties(self) -> None:
            person_factory(
                team=self.team, distinct_ids=["distinct_id"], properties={"email": "someone@gmail.com"},
            )
            person_factory(
                team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com"},
            )
            person_factory(team=self.team, distinct_ids=["distinct_id_3"], properties={})

            response = self.client.get(
                "/api/person/?properties=%s" % json.dumps([{"key": "email", "operator": "is_set", "value": "is_set"}])
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 2)

            response = self.client.get(
                "/api/person/?properties=%s"
                % json.dumps([{"key": "email", "operator": "icontains", "value": "another@gm"}])
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)

        def test_person_property_names(self) -> None:
            person_factory(team=self.team, properties={"$browser": "whatever", "$os": "Mac OS X"})
            person_factory(team=self.team, properties={"random_prop": "asdf"})
            person_factory(team=self.team, properties={"random_prop": "asdf"})

            response = self.client.get("/api/person/properties/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertEqual(response_data[0]["name"], "random_prop")
            self.assertEqual(response_data[0]["count"], 2)
            self.assertEqual(response_data[2]["name"], "$os")
            self.assertEqual(response_data[2]["count"], 1)
            self.assertEqual(response_data[1]["name"], "$browser")
            self.assertEqual(response_data[1]["count"], 1)

        def test_person_property_values(self):
            person_factory(
                team=self.team, properties={"random_prop": "asdf", "some other prop": "with some text"},
            )
            person_factory(team=self.team, properties={"random_prop": "asdf"})
            person_factory(team=self.team, properties={"random_prop": "qwerty"})
            person_factory(team=self.team, properties={"something_else": "qwerty"})
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

        def test_filter_by_cohort(self):
            person_factory(
                team=self.team, distinct_ids=["person_1", "anonymous_id"], properties={"$os": "Chrome"},
            )
            person_factory(team=self.team, distinct_ids=["person_2"])

            cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"$os": "Chrome"}}])
            cohort.calculate_people()
            response = self.client.get(f"/api/person/?cohort={cohort.pk}")
            self.assertEqual(len(response.json()["results"]), 1, response)

        def test_filter_person_list(self):

            person1: Person = person_factory(
                team=self.team,
                distinct_ids=["distinct_id", "another_one"],
                properties={"email": "someone@gmail.com"},
                is_identified=True,
            )
            person2: Person = person_factory(
                team=self.team, distinct_ids=["distinct_id_2"], properties={"email": "another@gmail.com"},
            )

            # Filter by distinct ID
            response = self.client.get("/api/person/?distinct_id=distinct_id")  # must be exact matches
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(response.json()["results"][0]["id"], person1.pk)
            self.assertEqual(response.json()["results"][0]["is_identified"], True)

            response = self.client.get("/api/person/?distinct_id=another_one")  # can search on any of the distinct IDs
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(response.json()["results"][0]["id"], person1.pk)

            # Filter by email
            response = self.client.get("/api/person/?email=another@gmail.com")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(response.json()["results"][0]["id"], person2.pk)

            # Filter by key identifier
            for _identifier in ["another@gmail.com", "distinct_id_2"]:
                response = self.client.get(f"/api/person/?key_identifier={_identifier}")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(len(response.json()["results"]), 1)
                self.assertEqual(response.json()["results"][0]["id"], person2.pk)

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
            person_factory(
                team=another_team, distinct_ids=["distinct_id", "x_another_one"],
            )
            person_factory(
                team=another_team, distinct_ids=["x_distinct_id_2"], properties={"email": "team2_another@gmail.com"},
            )

            # Person in current team
            person: Person = person_factory(
                team=self.team, distinct_ids=["distinct_id"],
            )

            # Filter by distinct ID
            response = self.client.get("/api/person/?distinct_id=distinct_id")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(
                response.json()["results"][0]["id"], person.pk,
            )  # note that even with shared distinct IDs, only the person from the same team is returned

            response = self.client.get("/api/person/?distinct_id=x_another_one")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["results"], [])

            # Filter by key identifier
            for _identifier in ["x_another_one", "distinct_id_2"]:
                response = self.client.get(f"/api/person/?key_identifier={_identifier}")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.json()["results"], [])

        def test_filter_is_identified(self):
            person_anonymous = person_factory(team=self.team, distinct_ids=["xyz"])
            person_identified_already = person_factory(team=self.team, distinct_ids=["tuv"], is_identified=True)

            # all
            response = self.client.get(
                "/api/person",
            )  # Make sure the endpoint works with and without the trailing slash
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 2)

            # anonymous
            response = self.client.get("/api/person/?is_identified=false")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(response.json()["results"][0]["id"], person_anonymous.id)
            self.assertEqual(response.json()["results"][0]["is_identified"], False)

            # identified
            response = self.client.get("/api/person/?is_identified=true")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 1)
            self.assertEqual(response.json()["results"][0]["id"], person_identified_already.id)
            self.assertEqual(response.json()["results"][0]["is_identified"], True)

        def test_delete_person(self):
            person = person_factory(
                team=self.team, distinct_ids=["person_1", "anonymous_id"], properties={"$os": "Chrome"},
            )
            event_factory(event="test", team=self.team, distinct_id="person_1")
            event_factory(event="test", team=self.team, distinct_id="anonymous_id")
            event_factory(event="test", team=self.team, distinct_id="someone_else")

            response = self.client.delete(f"/api/person/{person.pk}/")
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertEqual(response.content, b"")  # Empty response
            self.assertEqual(len(get_people()), 0)
            self.assertEqual(len(get_events()), 1)

            response = self.client.delete(f"/api/person/{person.pk}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_filter_id_or_uuid(self) -> None:
            person1 = person_factory(team=self.team, properties={"$browser": "whatever", "$os": "Mac OS X"})
            person2 = person_factory(team=self.team, properties={"random_prop": "asdf"})
            person_factory(team=self.team, properties={"random_prop": "asdf"})

            response = self.client.get("/api/person/?id={},{}".format(person1.id, person2.id))
            response_uuid = self.client.get("/api/person/?uuid={},{}".format(person1.uuid, person2.uuid))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), response_uuid.json())
            self.assertEqual(len(response.json()["results"]), 2)

        @mock.patch("posthog.api.capture.capture_internal")
        def test_merge_people(self, mock_capture_internal) -> None:
            # created first
            person3 = person_factory(team=self.team, distinct_ids=["3"], properties={"oh": "hello"})
            person1 = person_factory(
                team=self.team, distinct_ids=["1"], properties={"$browser": "whatever", "$os": "Mac OS X"}
            )
            person2 = person_factory(team=self.team, distinct_ids=["2"], properties={"random_prop": "asdf"})

            self.client.post(
                "/api/person/%s/merge/" % person1.pk, {"ids": [person2.pk, person3.pk]},
            )
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
                        {"event": "$create_alias", "properties": {"alias": "3"}},
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

        def test_return_non_anonymous_name(self) -> None:
            person_factory(
                team=self.team,
                distinct_ids=["distinct_id1", "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c"],
            )
            person_factory(
                team=self.team, distinct_ids=["17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c", "distinct_id2"],
            )

            response = self.client.get("/api/person/").json()

            self.assertEqual(response["results"][0]["name"], "distinct_id2")
            self.assertEqual(response["results"][1]["name"], "distinct_id1")

            self.assertEqual(
                response["results"][0]["distinct_ids"],
                ["distinct_id2", "17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c"],
            )
            self.assertEqual(
                response["results"][1]["distinct_ids"],
                ["distinct_id1", "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c"],
            )

        def test_person_cohorts(self) -> None:
            person_factory(team=self.team, distinct_ids=["1"], properties={"$some_prop": "something", "number": 1})
            person2 = person_factory(
                team=self.team, distinct_ids=["2"], properties={"$some_prop": "something", "number": 2}
            )
            cohort1 = Cohort.objects.create(
                team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
            )
            cohort2 = Cohort.objects.create(team=self.team, groups=[{"properties": {"number": 1}}], name="cohort2")
            cohort3 = Cohort.objects.create(team=self.team, groups=[{"properties": {"number": 2}}], name="cohort3")
            cohort1.calculate_people()
            cohort2.calculate_people()
            cohort3.calculate_people()

            response = self.client.get(f"/api/person/cohorts/?person_id={person2.id}").json()
            response["results"].sort(key=lambda cohort: cohort["name"])
            self.assertEqual(len(response["results"]), 2)
            self.assertDictContainsSubset({"id": cohort1.id, "count": 2, "name": cohort1.name}, response["results"][0])
            self.assertDictContainsSubset({"id": cohort3.id, "count": 1, "name": cohort3.name}, response["results"][1])

    return TestPerson


class TestPerson(
    factory_test_person(Event.objects.create, Person.objects.create, Event.objects.all, Person.objects.all)  # type: ignore
):
    pass
