from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Action, ActionStep, Event, Filter, Person, Team
from posthog.queries.stickiness import Stickiness


# parameterize tests to reuse in EE
def stickiness_test_factory(stickiness, event_factory, person_factory, action_factory):
    class TestStickiness(BaseTest):
        def _create_multiple_people(self):
            person_factory(team_id=self.team.id, distinct_ids=["person1"], properties={"name": "person1"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person1", timestamp="2020-01-01T12:00:00Z",
            )

            person_factory(team_id=self.team.id, distinct_ids=["person2"], properties={"name": "person2"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )
            # same day
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )

            person_factory(team_id=self.team.id, distinct_ids=["person3a", "person3b"], properties={"name": "person3"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3a", timestamp="2020-01-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3b", timestamp="2020-01-02T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3a", timestamp="2020-01-03T12:00:00Z",
            )

            person_factory(team_id=self.team.id, distinct_ids=["person4"], properties={"name": "person4"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person4", timestamp="2020-01-05T12:00:00Z",
            )

        def test_stickiness(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                filter = Filter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                    }
                )
                response = stickiness().run(filter, self.team)

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
            self._create_multiple_people()
            watched_movie = action_factory(team=self.team, name="watch movie action", event_name="watched movie")

            with freeze_time("2020-01-08T13:01:01Z"):
                filter = Filter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "actions": [{"id": watched_movie.pk}],
                    }
                )
                response = stickiness().run(filter, self.team)
            self.assertEqual(response[0]["label"], "watch movie action")
            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")

    return TestStickiness


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=event_name)
    action.calculate_events()
    return action


class DjangoStickinessTest(stickiness_test_factory(Stickiness, Event.objects.create, Person.objects.create, _create_action)):  # type: ignore
    pass
