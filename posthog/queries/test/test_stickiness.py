from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun import freeze_time

from posthog.models import Action, ActionStep, Event, Person, Team
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.stickiness import Stickiness
from posthog.test.base import BaseTest


# parameterize tests to reuse in EE
def stickiness_test_factory(stickiness, event_factory, person_factory, action_factory):
    class TestStickiness(BaseTest):
        def _create_multiple_people(self, period=timedelta(days=1)):
            base_time = datetime.fromisoformat("2020-01-01T12:00:00.000000")
            person_factory(team_id=self.team.id, distinct_ids=["person1"], properties={"name": "person1"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person1",
                timestamp=base_time.replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )

            person_factory(team_id=self.team.id, distinct_ids=["person2"], properties={"name": "person2"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp=base_time.replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp=(base_time + period).replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )
            # same day
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp=(base_time + period).replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )

            person_factory(team_id=self.team.id, distinct_ids=["person3a", "person3b"], properties={"name": "person3"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3a",
                timestamp=(base_time).replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3b",
                timestamp=(base_time + period).replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3a",
                timestamp=(base_time + period * 2).replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )

            person_factory(team_id=self.team.id, distinct_ids=["person4"], properties={"name": "person4"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person4",
                timestamp=(base_time + period * 4).replace(tzinfo=timezone.utc).isoformat(),
                properties={"$browser": "Chrome"},
            )

        def test_stickiness(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                    },
                    team=self.team,
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

        def test_stickiness_all_time(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                filter = StickinessFilter(
                    data={"shown_as": "Stickiness", "date_from": "all", "events": [{"id": "watched movie"}],},
                    team=self.team,
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

        def test_stickiness_minutes(self):
            self._create_multiple_people(period=timedelta(minutes=1))

            with freeze_time("2020-01-01T12:08:01Z"):
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01T12:00:00.00Z",
                        "date_to": "2020-01-01T12:08:00.00Z",
                        "events": [{"id": "watched movie"}],
                        "interval": "minute",
                    },
                    team=self.team,
                )
                response = stickiness().run(filter, self.team)

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 minute")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 minutes")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 minutes")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 minutes")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_hours(self):
            self._create_multiple_people(period=timedelta(hours=1))

            with freeze_time("2020-01-01T20:01:01Z"):
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01T12:00:00.00Z",
                        "date_to": "2020-01-01T20:00:00.00Z",
                        "events": [{"id": "watched movie"}],
                        "interval": "hour",
                    },
                    team=self.team,
                )
                response = stickiness().run(filter, self.team)

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 hour")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 hours")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 hours")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 hours")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_weeks(self):
            self._create_multiple_people(period=timedelta(weeks=1))

            with freeze_time("2020-02-15T13:01:01Z"):
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-02-15",
                        "events": [{"id": "watched movie"}],
                        "interval": "week",
                    },
                    team=self.team,
                )
                response = stickiness().run(filter, self.team)

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 week")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 weeks")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 weeks")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 weeks")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_months(self):
            self._create_multiple_people(period=relativedelta(months=1))

            with freeze_time("2020-02-08T13:01:01Z"):
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-09-08",
                        "events": [{"id": "watched movie"}],
                        "interval": "month",
                    },
                    team=self.team,
                )
                response = stickiness().run(filter, self.team)

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 month")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 months")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 months")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 months")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_prop_filter(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                        "properties": [{"key": "$browser", "value": "Chrome"}],
                    },
                    team=self.team,
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
                filter = StickinessFilter(
                    data={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "actions": [{"id": watched_movie.pk}],
                    },
                    team=self.team,
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
