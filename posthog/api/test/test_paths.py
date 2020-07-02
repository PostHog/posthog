from .base import BaseTest
from posthog.models import Person, Event, Element
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time


class TestPaths(BaseTest):
    TESTS_API = True

    def test_current_url_paths_and_logic(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )

        person2 = Person.objects.create(team=self.team, distinct_ids=["person_2"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_3"])
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_4"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_4",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_4",
            event="$pageview",
            team=self.team,
        )

        response = self.client.get("/api/paths/").json()
        self.assertEqual(response[0]["source"], "1_/", response)
        self.assertEqual(response[0]["target"], "2_/pricing")
        self.assertEqual(response[0]["value"], 2)

        self.assertEqual(response[1]["source"], "1_/")
        self.assertEqual(response[1]["target"], "2_/about")
        self.assertEqual(response[1]["value"], 1)

        self.assertEqual(response[2]["source"], "1_/pricing")
        self.assertEqual(response[2]["target"], "2_/")
        self.assertEqual(response[2]["value"], 1)

        self.assertEqual(response[3]["source"], "2_/pricing", response[3])
        self.assertEqual(response[3]["target"], "3_/about")
        self.assertEqual(response[3]["value"], 1)

        date_from = now() - relativedelta(days=7)
        response = self.client.get(
            "/api/paths/?date_from=" + date_from.strftime("%Y-%m-%d")
        ).json()
        self.assertEqual(len(response), 4)

        date_to = now() + relativedelta(days=7)
        response = self.client.get(
            "/api/paths/?date_to=" + date_to.strftime("%Y-%m-%d")
        ).json()
        self.assertEqual(len(response), 4)

        date_from = now() + relativedelta(days=7)
        response = self.client.get(
            "/api/paths/?date_from=" + date_from.strftime("%Y-%m-%d")
        ).json()
        self.assertEqual(len(response), 0)

        date_to = now() - relativedelta(days=7)
        response = self.client.get(
            "/api/paths/?date_to=" + date_to.strftime("%Y-%m-%d")
        ).json()
        self.assertEqual(len(response), 0)

        date_from = now() - relativedelta(days=7)
        date_to = now() + relativedelta(days=7)
        response = self.client.get(
            "/api/paths/?date_from="
            + date_from.strftime("%Y-%m-%d")
            + "&date_to="
            + date_to.strftime("%Y-%m-%d")
        ).json()
        self.assertEqual(len(response), 4)

        date_from = now() + relativedelta(days=7)
        date_to = now() - relativedelta(days=7)
        response = self.client.get(
            "/api/paths/?date_from="
            + date_from.strftime("%Y-%m-%d")
            + "&date_to="
            + date_to.strftime("%Y-%m-%d")
        ).json()
        self.assertEqual(len(response), 0)

    def test_custom_event_paths(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            distinct_id="person_1", event="custom_event_1", team=self.team
        )
        Event.objects.create(
            distinct_id="person_1", event="custom_event_3", team=self.team
        )
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )  # should be ignored

        person2 = Person.objects.create(team=self.team, distinct_ids=["person_2"])
        Event.objects.create(
            distinct_id="person_2", event="custom_event_1", team=self.team
        )
        Event.objects.create(
            distinct_id="person_2", event="custom_event_2", team=self.team
        )
        Event.objects.create(
            distinct_id="person_2", event="custom_event_3", team=self.team
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_3"])
        Event.objects.create(
            distinct_id="person_3", event="custom_event_2", team=self.team
        )
        Event.objects.create(
            distinct_id="person_3", event="custom_event_1", team=self.team
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_4"])
        Event.objects.create(
            distinct_id="person_4", event="custom_event_1", team=self.team
        )
        Event.objects.create(
            distinct_id="person_4", event="custom_event_2", team=self.team
        )

        response = self.client.get("/api/paths/?type=custom_event").json()
        self.assertEqual(response[0]["source"], "1_custom_event_1", response)
        self.assertEqual(response[0]["target"], "2_custom_event_2")
        self.assertEqual(response[0]["value"], 2)

        self.assertEqual(response[1]["source"], "1_custom_event_1")
        self.assertEqual(response[1]["target"], "2_custom_event_3")
        self.assertEqual(response[1]["value"], 1)

        self.assertEqual(response[2]["source"], "1_custom_event_2")
        self.assertEqual(response[2]["target"], "2_custom_event_1")
        self.assertEqual(response[2]["value"], 1)

        self.assertEqual(response[3]["source"], "2_custom_event_2", response[3])
        self.assertEqual(response[3]["target"], "3_custom_event_3")
        self.assertEqual(response[3]["value"], 1)

    def test_screen_paths(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            properties={"$screen_name": "/"},
            distinct_id="person_1",
            event="$screen",
            team=self.team,
        )
        Event.objects.create(
            properties={"$screen_name": "/about"},
            distinct_id="person_1",
            event="$screen",
            team=self.team,
        )

        person2 = Person.objects.create(team=self.team, distinct_ids=["person_2"])
        Event.objects.create(
            properties={"$screen_name": "/"},
            distinct_id="person_2",
            event="$screen",
            team=self.team,
        )
        Event.objects.create(
            properties={"$screen_name": "/pricing"},
            distinct_id="person_2",
            event="$screen",
            team=self.team,
        )
        Event.objects.create(
            properties={"$screen_name": "/about"},
            distinct_id="person_2",
            event="$screen",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_3"])
        Event.objects.create(
            properties={"$screen_name": "/pricing"},
            distinct_id="person_3",
            event="$screen",
            team=self.team,
        )
        Event.objects.create(
            properties={"$screen_name": "/"},
            distinct_id="person_3",
            event="$screen",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_4"])
        Event.objects.create(
            properties={"$screen_name": "/"},
            distinct_id="person_4",
            event="$screen",
            team=self.team,
        )
        Event.objects.create(
            properties={"$screen_name": "/pricing"},
            distinct_id="person_4",
            event="$screen",
            team=self.team,
        )

        response = self.client.get("/api/paths/?type=%24screen").json()
        self.assertEqual(response[0]["source"], "1_/", response)
        self.assertEqual(response[0]["target"], "2_/pricing")
        self.assertEqual(response[0]["value"], 2)

        self.assertEqual(response[1]["source"], "1_/")
        self.assertEqual(response[1]["target"], "2_/about")
        self.assertEqual(response[1]["value"], 1)

        self.assertEqual(response[2]["source"], "1_/pricing")
        self.assertEqual(response[2]["target"], "2_/")
        self.assertEqual(response[2]["value"], 1)

        self.assertEqual(response[3]["source"], "2_/pricing", response[3])
        self.assertEqual(response[3]["target"], "3_/about")
        self.assertEqual(response[3]["value"], 1)

    def test_autocapture_paths(self):
        Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            event="$autocapture",
            team=self.team,
            distinct_id="person_1",
            elements=[
                Element(
                    tag_name="a",
                    text="hello",
                    href="/a-url",
                    nth_child=1,
                    nth_of_type=0,
                    order=1,
                ),
                Element(tag_name="button", nth_child=0, nth_of_type=0, order=2),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=3),
                Element(
                    tag_name="div",
                    nth_child=0,
                    nth_of_type=0,
                    order=4,
                    attr_id="nested",
                ),
            ],
        )

        Event.objects.create(
            event="$autocapture",
            team=self.team,
            distinct_id="person_1",
            elements=[
                Element(
                    tag_name="a",
                    text="goodbye",
                    nth_child=2,
                    nth_of_type=0,
                    order=0,
                    attr_id="someId",
                ),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=1),
                # make sure elements don't get double counted if they're part of the same event
                Element(href="/a-url-2", nth_child=0, nth_of_type=0, order=2),
            ],
        )

        Person.objects.create(team=self.team, distinct_ids=["person_2"])
        Event.objects.create(
            event="$autocapture",
            team=self.team,
            distinct_id="person_2",
            elements=[
                Element(
                    tag_name="a",
                    text="hello1",
                    href="/a-url",
                    nth_child=1,
                    nth_of_type=0,
                    order=1,
                ),
                Element(tag_name="button", nth_child=0, nth_of_type=0, order=2),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=3),
                Element(
                    tag_name="div",
                    nth_child=0,
                    nth_of_type=0,
                    order=4,
                    attr_id="nested",
                ),
            ],
        )

        Event.objects.create(
            event="$autocapture",
            team=self.team,
            distinct_id="person_2",
            elements=[
                Element(
                    tag_name="a",
                    text="goodbye1",
                    nth_child=2,
                    nth_of_type=0,
                    order=0,
                    attr_id="someId",
                ),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=1),
                # make sure elements don't get double counted if they're part of the same event
                Element(href="/a-url-2", nth_child=0, nth_of_type=0, order=2),
            ],
        )
        response = self.client.get("/api/paths/?type=%24autocapture").json()
        self.assertEqual(response[0]["source"], "1_<a> hello")
        self.assertEqual(response[0]["target"], "2_<a> goodbye")
        self.assertEqual(response[0]["value"], 1)

        self.assertEqual(response[1]["source"], "1_<a> hello1")
        self.assertEqual(response[1]["target"], "2_<a> goodbye1")
        self.assertEqual(response[1]["value"], 1)

        elements = self.client.get("/api/paths/elements/").json()
        self.assertEqual(elements[0]["name"], "<a> hello")
        self.assertEqual(elements[1]["name"], "<a> goodbye")
        self.assertEqual(len(elements), 4)

    def test_paths_properties_filter(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            properties={"$current_url": "/", "$browser": "Chrome"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about", "$browser": "Chrome"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )

        person2 = Person.objects.create(team=self.team, distinct_ids=["person_2"])
        Event.objects.create(
            properties={"$current_url": "/", "$browser": "Chrome"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/pricing", "$browser": "Chrome"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about", "$browser": "Chrome"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_3"])
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_4"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_4",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_4",
            event="$pageview",
            team=self.team,
        )

        response = self.client.get(
            '/api/paths/?properties=%5B%7B"key"%3A"%24browser"%2C"value"%3A"Chrome"%2C"type"%3A"event"%7D%5D'
        ).json()

        self.assertEqual(response[0]["source"], "1_/")
        self.assertEqual(response[0]["target"], "2_/about")
        self.assertEqual(response[0]["value"], 1)

        self.assertEqual(response[1]["source"], "1_/")
        self.assertEqual(response[1]["target"], "2_/pricing")
        self.assertEqual(response[1]["value"], 1)

        self.assertEqual(response[2]["source"], "2_/pricing")
        self.assertEqual(response[2]["target"], "3_/about")
        self.assertEqual(response[2]["value"], 1)

    def test_paths_start(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
        )

        person2 = Person.objects.create(team=self.team, distinct_ids=["person_2"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/about"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_3"])
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person_4"])
        Event.objects.create(
            properties={"$current_url": "/"},
            distinct_id="person_4",
            event="$pageview",
            team=self.team,
        )
        Event.objects.create(
            properties={"$current_url": "/pricing"},
            distinct_id="person_4",
            event="$pageview",
            team=self.team,
        )

        response = self.client.get(
            "/api/paths/?type=%24pageview&start=%2Fpricing"
        ).json()
        for item in response:
            self.assertEqual(item["source"], "1_/pricing")

    def test_paths_in_window(self):
        Person.objects.create(team=self.team, distinct_ids=["person_1"])

        with freeze_time("2020-04-14T03:25:34.000Z"):
            Event.objects.create(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            )
        with freeze_time("2020-04-14T03:30:34.000Z"):
            Event.objects.create(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            )

        with freeze_time("2020-04-15T03:25:34.000Z"):
            Event.objects.create(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            )
        with freeze_time("2020-04-15T03:30:34.000Z"):
            Event.objects.create(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            )

        response = self.client.get("/api/paths/?date_from=2020-04-13").json()
        self.assertEqual(response[0]["source"], "1_/")
        self.assertEqual(response[0]["target"], "2_/about")
        self.assertEqual(response[0]["value"], 2)
