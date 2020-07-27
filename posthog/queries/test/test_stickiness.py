from posthog.queries.stickiness import Stickiness
from posthog.api.test.base import BaseTest
from posthog.models import Action, Person, Event, ActionStep, Team, Filter
from freezegun import freeze_time


class TestStickiness(BaseTest):
    def _create_multiple_people(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person1"], properties={"name": "person1"})
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person1", timestamp="2020-01-01T12:00:00Z",
        )

        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"], properties={"name": "person2"})
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-01T12:00:00Z",
        )
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
        )
        # same day
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
        )

        person3 = Person.objects.create(team=self.team, distinct_ids=["person3"], properties={"name": "person3"})
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-01T12:00:00Z",
        )
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-02T12:00:00Z",
        )
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-03T12:00:00Z",
        )

        person4 = Person.objects.create(team=self.team, distinct_ids=["person4"], properties={"name": "person4"})
        Event.objects.create(
            team=self.team, event="watched movie", distinct_id="person4", timestamp="2020-01-05T12:00:00Z",
        )
        return (person1, person2, person3, person4)

    def test_stickiness(self):
        person1 = self._create_multiple_people()[0]

        with freeze_time("2020-01-08T13:01:01Z"):
            filter = Filter(
                data={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    "events": [{"id": "watched movie"}],
                }
            )
            response = Stickiness().run(filter, self.team)

        self.assertEqual(response[0]["count"], 4)
        self.assertEqual(response[0]["labels"][0], "1 day")
        self.assertEqual(response[0]["data"][0], 2)
        self.assertEqual(response[0]["labels"][1], "2 days")
        self.assertEqual(response[0]["data"][1], 1)
        self.assertEqual(response[0]["labels"][2], "3 days")
        self.assertEqual(response[0]["data"][2], 1)
        self.assertEqual(response[0]["labels"][6], "7 days")
        self.assertEqual(response[0]["data"][6], 0)

    def test_stickiness_action(self):
        person1 = self._create_multiple_people()[0]

        watched_movie = Action.objects.create(team=self.team, name="watch movie action")
        ActionStep.objects.create(action=watched_movie, event="watched movie")
        watched_movie.calculate_events()

        with freeze_time("2020-01-08T13:01:01Z"):
            filter = Filter(
                data={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    "actions": [{"id": watched_movie.pk}],
                }
            )
            response = Stickiness().run(filter, self.team)
        self.assertEqual(response[0]["label"], "watch movie action")
        self.assertEqual(response[0]["count"], 4)
        self.assertEqual(response[0]["labels"][0], "1 day")
