from .base import BaseTest
from posthog.models import Person, Event, Cohort
import json


class TestPerson(BaseTest):
    TESTS_API = True

    def test_search(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["distinct_id"],
            properties={"email": "someone@gmail.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["distinct_id_3"], properties={}
        )

        response = self.client.get("/api/person/?search=has:email").json()
        self.assertEqual(len(response["results"]), 2)

        response = self.client.get("/api/person/?search=another@gm").json()
        self.assertEqual(len(response["results"]), 1)

    def test_properties(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["distinct_id"],
            properties={"email": "someone@gmail.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["distinct_id_3"], properties={}
        )

        response = self.client.get(
            "/api/person/?properties=%s"
            % json.dumps([{"key": "email", "operator": "is_set", "value": "true"}])
        ).json()
        self.assertEqual(len(response["results"]), 2)

        response = self.client.get(
            "/api/person/?properties=%s"
            % json.dumps(
                [{"key": "email", "operator": "icontains", "value": "another@gm"}]
            )
        ).json()
        self.assertEqual(len(response["results"]), 1)

    def test_person_property_names(self):
        Person.objects.create(
            team=self.team, properties={"$browser": "whatever", "$os": "Mac OS X"}
        )
        Person.objects.create(team=self.team, properties={"random_prop": "asdf"})
        Person.objects.create(team=self.team, properties={"random_prop": "asdf"})

        response = self.client.get("/api/person/properties/").json()
        self.assertEqual(response[0]["name"], "random_prop")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[2]["name"], "$os")
        self.assertEqual(response[2]["count"], 1)
        self.assertEqual(response[1]["name"], "$browser")
        self.assertEqual(response[1]["count"], 1)

    def test_person_property_values(self):
        Person.objects.create(
            team=self.team,
            properties={"random_prop": "asdf", "some other prop": "with some text"},
        )
        Person.objects.create(team=self.team, properties={"random_prop": "asdf"})
        Person.objects.create(team=self.team, properties={"random_prop": "qwerty"})
        Person.objects.create(team=self.team, properties={"something_else": "qwerty"})
        response = self.client.get("/api/person/values/?key=random_prop").json()
        self.assertEqual(response[0]["name"], "asdf")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[1]["name"], "qwerty")
        self.assertEqual(response[1]["count"], 1)
        self.assertEqual(len(response), 2)

        response = self.client.get(
            "/api/person/values/?key=random_prop&value=qw"
        ).json()
        self.assertEqual(response[0]["name"], "qwerty")
        self.assertEqual(response[0]["count"], 1)

    def test_filter_by_cohort(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
        )
        Person.objects.create(team=self.team, distinct_ids=["person_2"])

        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$os": "Chrome"}}]
        )
        cohort.calculate_people()
        response = self.client.get("/api/person/?cohort=%s" % cohort.pk).json()
        self.assertEqual(len(response["results"]), 1, response)

    def test_delete_person(self):
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
        )
        Event.objects.create(team=self.team, distinct_id="person_1")
        Event.objects.create(team=self.team, distinct_id="anonymous_id")
        Event.objects.create(team=self.team, distinct_id="someone_else")

        response = self.client.delete("/api/person/%s/" % person.pk)
        self.assertEqual(Person.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 1)
