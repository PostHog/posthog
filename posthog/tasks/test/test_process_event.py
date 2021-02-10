from datetime import timedelta
from typing import Any, Callable, List, Union
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import (
    Action,
    ActionStep,
    Element,
    ElementGroup,
    Event,
    FeatureFlag,
    Organization,
    Person,
    SessionRecordingEvent,
    Team,
    User,
)
from posthog.tasks.process_event import process_event as _process_event
from posthog.test.base import BaseTest


def get_elements(event_id: Union[int, UUID]) -> List[Element]:
    event = Event.objects.get(pk=event_id)
    return [e for e in ElementGroup.objects.get(hash=event.elements_hash).element_set.all().order_by("order")]


def test_process_event_factory(
    process_event: Callable, get_events: Callable, get_session_recording_events: Callable, get_elements: Callable
) -> Callable:
    class TestProcessEvent(BaseTest):
        def test_capture_new_person(self) -> None:
            user = self._create_user("tim")
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action1, selector="a", event="$autocapture")
            action2 = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action2, selector="a", event="$autocapture")
            team_id = self.team.pk
            self.team.ingested_event = True  # avoid sending `first team event ingested` to PostHog
            self.team.save()

            num_queries = 28
            if settings.EE_AVAILABLE:  # extra queries to check for hooks
                num_queries += 4
            if settings.MULTI_TENANCY:  # extra query to check for billing plan
                num_queries += 1
            with self.assertNumQueries(num_queries):
                process_event(
                    2,
                    "",
                    "",
                    {
                        "event": "$autocapture",
                        "properties": {
                            "distinct_id": 2,
                            "token": self.team.api_token,
                            "$elements": [
                                {"tag_name": "a", "nth_child": 1, "nth_of_type": 2, "attr__class": "btn btn-sm",},
                                {"tag_name": "div", "nth_child": 1, "nth_of_type": 2, "$el_text": "💻",},
                            ],
                        },
                    },
                    team_id,
                    now().isoformat(),
                    now().isoformat(),
                )

            self.assertEqual(Person.objects.get().distinct_ids, ["2"])
            event = get_events()[0]
            self.assertEqual(event.event, "$autocapture")
            elements = get_elements(event.id)
            self.assertEqual(elements[0].tag_name, "a")
            self.assertEqual(elements[0].attr_class, ["btn", "btn-sm"])
            self.assertEqual(elements[1].order, 1)
            self.assertEqual(elements[1].text, "💻")
            self.assertEqual(event.distinct_id, "2")
            team = Team.objects.get()
            self.assertEqual(team.event_names, ["$autocapture"])
            self.assertEqual(
                team.event_names_with_usage, [{"event": "$autocapture", "volume": None, "usage_count": None,}]
            )
            self.assertEqual(team.event_properties, ["distinct_id", "token", "$ip"])
            self.assertEqual(
                team.event_properties_with_usage,
                [
                    {"key": "distinct_id", "usage_count": None, "volume": None},
                    {"key": "token", "usage_count": None, "volume": None},
                    {"key": "$ip", "usage_count": None, "volume": None},
                ],
            )

        def test_capture_no_element(self) -> None:
            user = self._create_user("tim")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            process_event(
                "asdfasdfasdf",
                "",
                "",
                {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(Person.objects.get().distinct_ids, ["asdfasdfasdf"])
            event = get_events()[0]
            self.assertEqual(event.event, "$pageview")

        def test_capture_sent_at(self) -> None:
            self._create_user("tim")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            right_now = now()
            tomorrow = right_now + timedelta(days=1, hours=2)
            tomorrow_sent_at = right_now + timedelta(days=1, hours=2, minutes=10)

            # event sent_at 10 minutes after timestamp
            process_event(
                "movie played",
                "",
                "",
                {
                    "event": "$pageview",
                    "timestamp": tomorrow.isoformat(),
                    "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},
                },
                self.team.pk,
                right_now.isoformat(),
                tomorrow_sent_at.isoformat(),
            )

            event = get_events()[0]

            event_seconds_before_now = (right_now - event.timestamp).seconds

            # assert that the event is actually recorded 10 minutes before now
            self.assertGreater(event_seconds_before_now, 590)
            self.assertLess(event_seconds_before_now, 610)

        def test_capture_sent_at_no_timezones(self) -> None:
            self._create_user("tim")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            right_now = now()
            tomorrow = right_now + timedelta(days=1, hours=2)
            tomorrow_sent_at = right_now + timedelta(days=1, hours=2, minutes=10)

            # remove timezones
            tomorrow = tomorrow.replace(tzinfo=None)
            tomorrow_sent_at = tomorrow_sent_at.replace(tzinfo=None)

            # event sent_at 10 minutes after timestamp
            process_event(
                "movie played",
                "",
                "",
                {
                    "event": "$pageview",
                    "timestamp": tomorrow.isoformat(),
                    "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},
                },
                self.team.pk,
                right_now.isoformat(),
                tomorrow_sent_at.isoformat(),
            )

            event = get_events()[0]

            event_seconds_before_now = (right_now - event.timestamp).seconds

            # assert that the event is actually recorded 10 minutes before now
            self.assertGreater(event_seconds_before_now, 590)
            self.assertLess(event_seconds_before_now, 610)

        def test_capture_no_sent_at(self) -> None:
            self._create_user("james")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            right_now = now()
            tomorrow = right_now + timedelta(days=1, hours=2)

            # event sent_at 10 minutes after timestamp
            process_event(
                "movie played",
                "",
                "",
                {
                    "event": "$pageview",
                    "timestamp": tomorrow.isoformat(),
                    "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},
                },
                self.team.pk,
                right_now.isoformat(),
                None,
            )

            event = get_events()[0]

            difference = abs((tomorrow - event.timestamp).seconds)

            self.assertLess(difference, 1)

        def test_ip_capture(self) -> None:
            user = self._create_user("tim")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            process_event(
                "asdfasdfasdf",
                "11.12.13.14",
                "",
                {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            event = get_events()[0]
            self.assertEqual(event.properties["$ip"], "11.12.13.14")

        def test_ip_override(self) -> None:
            user = self._create_user("tim")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            process_event(
                "asdfasdfasdf",
                "11.12.13.14",
                "",
                {
                    "event": "$pageview",
                    "properties": {"$ip": "1.0.0.1", "distinct_id": "asdfasdfasdf", "token": self.team.api_token,},
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            event = get_events()[0]
            self.assertEqual(event.properties["$ip"], "1.0.0.1")

        def test_anonymized_ip_capture(self) -> None:
            self.team.anonymize_ips = True
            self.team.save()

            user = self._create_user("tim")
            Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

            process_event(
                "asdfasdfasdf",
                "11.12.13.14",
                "",
                {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            event = get_events()[0]
            self.assertNotIn("$ip", event.properties.keys())

        def test_alias(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "alias": "old_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])

        def test_alias_reverse(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])

            process_event(
                "old_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "old_distinct_id",
                        "token": self.team.api_token,
                        "alias": "new_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])

        def test_alias_twice(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "alias": "old_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            Person.objects.create(team=self.team, distinct_ids=["old_distinct_id_2"])

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "alias": "old_distinct_id_2",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 2)
            self.assertEqual(
                Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id", "old_distinct_id_2"],
            )

        def test_alias_before_person(self) -> None:
            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "alias": "old_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            person1 = Person.objects.get(team=self.team, persondistinctid__distinct_id="old_distinct_id")
            person2 = Person.objects.get(team=self.team, persondistinctid__distinct_id="new_distinct_id")

            self.assertEqual(person1, person2)

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(Person.objects.get().distinct_ids, ["new_distinct_id", "old_distinct_id"])

        def test_alias_both_existing(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])
            Person.objects.create(team=self.team, distinct_ids=["new_distinct_id"])

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "alias": "old_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])

        def test_offset_timestamp(self) -> None:
            with freeze_time("2020-01-01T12:00:05.200Z"):
                process_event(
                    "distinct_id",
                    "",
                    "",
                    {"offset": 150, "event": "$autocapture", "distinct_id": "distinct_id",},
                    self.team.pk,
                    now().isoformat(),
                    now().isoformat(),
                )  # sent at makes no difference for offset

            event = get_events()[0]
            self.assertEqual(event.timestamp.isoformat(), "2020-01-01T12:00:05.050000+00:00")

        def test_offset_timestamp_no_sent_at(self) -> None:
            with freeze_time("2020-01-01T12:00:05.200Z"):
                process_event(
                    "distinct_id",
                    "",
                    "",
                    {"offset": 150, "event": "$autocapture", "distinct_id": "distinct_id",},
                    self.team.pk,
                    now().isoformat(),
                    None,
                )  # no sent at makes no difference for offset

            event = get_events()[0]
            self.assertEqual(event.timestamp.isoformat(), "2020-01-01T12:00:05.050000+00:00")

        def test_alias_merge_properties(self) -> None:
            Person.objects.create(
                team=self.team,
                distinct_ids=["old_distinct_id"],
                properties={"key_on_both": "old value both", "key_on_old": "old value"},
            )

            Person.objects.create(
                team=self.team,
                distinct_ids=["new_distinct_id"],
                properties={"key_on_both": "new value both", "key_on_new": "new value"},
            )

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$create_alias",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "alias": "old_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)

            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["old_distinct_id", "new_distinct_id"])
            self.assertEqual(
                person.properties,
                {"key_on_both": "new value both", "key_on_new": "new value", "key_on_old": "old value",},
            )

        def test_long_htext(self) -> None:
            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$autocapture",
                    "properties": {
                        "distinct_id": "new_distinct_id",
                        "token": self.team.api_token,
                        "$elements": [
                            {
                                "tag_name": "a",
                                "$el_text": "a" * 2050,
                                "attr__href": "a" * 2050,
                                "nth_child": 1,
                                "nth_of_type": 2,
                                "attr__class": "btn btn-sm",
                            },
                        ],
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )
            event = get_events()[0]
            element = get_elements(event.id)[0]
            self.assertEqual(len(element.href), 2048)
            self.assertEqual(len(element.text), 400)

        @patch("posthog.tasks.process_event.posthoganalytics.capture")
        def test_capture_first_team_event(self, mock: Any) -> None:
            """
            Assert that we report to posthoganalytics the first event ingested by a team.
            """
            organization, team, user = User.objects.bootstrap(
                "Test", "testuser@posthog.com", None, team_fields={"api_token": 456}
            )

            process_event(
                2,
                "",
                "",
                {
                    "event": "$autocapture",
                    "properties": {
                        "distinct_id": 1,
                        "token": team.api_token,
                        "$elements": [
                            {"tag_name": "a", "nth_child": 1, "nth_of_type": 2, "attr__class": "btn btn-sm",},
                        ],
                    },
                },
                team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            mock.assert_called_once_with(user.distinct_id, "first team event ingested", {"team": str(team.uuid)})

            team.refresh_from_db()
            self.assertEqual(team.ingested_event, True)

        def test_snapshot_event_stored_as_session_recording_event(self) -> None:
            process_event(
                "some-id",
                "",
                "",
                {
                    "event": "$snapshot",
                    "properties": {"$session_id": "abcf-efg", "$snapshot_data": {"timestamp": 123,}},
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_session_recording_events()), 1)
            self.assertEqual(len(get_events()), 0)

            event = get_session_recording_events()[0]
            self.assertEqual(event.session_id, "abcf-efg")
            self.assertEqual(event.distinct_id, "some-id")
            self.assertEqual(event.snapshot_data, {"timestamp": 123,})

        def test_identify_set(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["distinct_id"])

            process_event(
                "distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "token": self.team.api_token,
                        "distinct_id": "distinct_id",
                        "$set": {"a_prop": "test-1", "c_prop": "test-1"},
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(get_events()[0].properties["$set"], {"a_prop": "test-1", "c_prop": "test-1"})
            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["distinct_id"])
            self.assertEqual(person.properties, {"a_prop": "test-1", "c_prop": "test-1"})

            # check no errors as this call can happen multiple times
            process_event(
                "distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "token": self.team.api_token,
                        "distinct_id": "distinct_id",
                        "$set": {"a_prop": "test-2", "b_prop": "test-2b"},
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 2)
            self.assertEqual(
                Person.objects.get().properties, {"a_prop": "test-2", "b_prop": "test-2b", "c_prop": "test-1"}
            )

        def test_identify_set_once(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["distinct_id"])

            process_event(
                "distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "token": self.team.api_token,
                        "distinct_id": "distinct_id",
                        "$set_once": {"a_prop": "test-1", "c_prop": "test-1"},
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(get_events()[0].properties["$set_once"], {"a_prop": "test-1", "c_prop": "test-1"})
            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["distinct_id"])
            self.assertEqual(person.properties, {"a_prop": "test-1", "c_prop": "test-1"})

            # check no errors as this call can happen multiple times
            process_event(
                "distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "token": self.team.api_token,
                        "distinct_id": "distinct_id",
                        "$set_once": {"a_prop": "test-2", "b_prop": "test-2"},
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 2)
            self.assertEqual(
                Person.objects.get().properties, {"a_prop": "test-1", "b_prop": "test-2", "c_prop": "test-1"}
            )

        def test_distinct_with_anonymous_id(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["anonymous_id"])

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "$anon_distinct_id": "anonymous_id",
                        "token": self.team.api_token,
                        "distinct_id": "new_distinct_id",
                        "$set": {"a_prop": "test"},
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            self.assertEqual(len(get_events()), 1)
            self.assertEqual(get_events()[0].properties["$set"], {"a_prop": "test"})
            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id"])
            self.assertEqual(person.properties, {"a_prop": "test"})

            # check no errors as this call can happen multiple times
            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "$anon_distinct_id": "anonymous_id",
                        "token": self.team.api_token,
                        "distinct_id": "new_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

        # This case is likely to happen after signup, for example:
        # 1. User browses website with anonymous_id
        # 2. User signs up, triggers event with their new_distinct_id (creating a new Person)
        # 3. In the frontend, try to alias anonymous_id with new_distinct_id
        # Result should be that we end up with one Person with both ID's
        def test_distinct_with_anonymous_id_which_was_already_created(self) -> None:
            Person.objects.create(team=self.team, distinct_ids=["anonymous_id"])
            Person.objects.create(
                team=self.team, distinct_ids=["new_distinct_id"], properties={"email": "someone@gmail.com"},
            )

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "$anon_distinct_id": "anonymous_id",
                        "token": self.team.api_token,
                        "distinct_id": "new_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            # self.assertEqual(len(get_events()), 0)
            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id"])
            self.assertEqual(person.properties["email"], "someone@gmail.com")

        def test_distinct_with_multiple_anonymous_ids_which_were_already_created(self,) -> None:
            # logging in the first time
            Person.objects.create(team=self.team, distinct_ids=["anonymous_id"])
            Person.objects.create(
                team=self.team, distinct_ids=["new_distinct_id"], properties={"email": "someone@gmail.com"},
            )

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "$anon_distinct_id": "anonymous_id",
                        "token": self.team.api_token,
                        "distinct_id": "new_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            # self.assertEqual(len(get_events()), 0)
            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id"])
            self.assertEqual(person.properties["email"], "someone@gmail.com")

            # logging in another time

            Person.objects.create(team=self.team, distinct_ids=["anonymous_id_2"])

            process_event(
                "new_distinct_id",
                "",
                "",
                {
                    "event": "$identify",
                    "properties": {
                        "$anon_distinct_id": "anonymous_id_2",
                        "token": self.team.api_token,
                        "distinct_id": "new_distinct_id",
                    },
                },
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )

            person = Person.objects.get()
            self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id", "anonymous_id_2"])
            self.assertEqual(person.properties["email"], "someone@gmail.com")

        def test_distinct_team_leakage(self) -> None:
            team2 = Organization.objects.bootstrap(None)[2]
            Person.objects.create(team=team2, distinct_ids=["2"], properties={"email": "team2@gmail.com"})
            Person.objects.create(team=self.team, distinct_ids=["1", "2"])

            try:
                process_event(
                    "2",
                    "",
                    "",
                    {
                        "event": "$identify",
                        "properties": {"$anon_distinct_id": "1", "token": self.team.api_token, "distinct_id": "2",},
                    },
                    self.team.pk,
                    now().isoformat(),
                    now().isoformat(),
                )
            except:
                pass

            people = Person.objects.all()
            self.assertEqual(people.count(), 2)
            self.assertEqual(people[1].team, self.team)
            self.assertEqual(people[1].properties, {})
            self.assertEqual(people[1].distinct_ids, ["1", "2"])
            self.assertEqual(people[0].team, team2)
            self.assertEqual(people[0].distinct_ids, ["2"])

        def test_set_is_identified(self) -> None:
            distinct_id = "777"
            person_before_event = Person.objects.create(team=self.team, distinct_ids=[distinct_id])
            self.assertFalse(person_before_event.is_identified)
            process_event(
                distinct_id,
                "",
                "",
                {"event": "$identify", "properties": {},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )
            person_after_event = Person.objects.get(team=self.team, persondistinctid__distinct_id=distinct_id)
            self.assertTrue(person_after_event.is_identified)

        def test_team_event_properties(self) -> None:
            self.assertListEqual(self.team.event_properties_numerical, [])
            process_event(
                "xxx",
                "",
                "",
                {"event": "purchase", "properties": {"price": 299.99, "name": "AirPods Pro"},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )
            self.team.refresh_from_db()
            self.assertListEqual(self.team.event_properties, ["price", "name", "$ip"])
            self.assertListEqual(self.team.event_properties_numerical, ["price"])

        def test_event_name_dict_json(self) -> None:
            process_event(
                "xxx",
                "",
                "",
                {"event": {"event name": "as object"}, "properties": {"price": 299.99, "name": "AirPods Pro"},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )
            event = get_events()[0]
            self.assertEqual(event.event, '{"event name": "as object"}')

        def test_event_name_list_json(self) -> None:
            process_event(
                "xxx",
                "",
                "",
                {"event": ["event name", "a list"], "properties": {"price": 299.99, "name": "AirPods Pro"},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )
            event = get_events()[0]
            self.assertEqual(event.event, '["event name", "a list"]')

        def test_long_event_name_substr(self) -> None:
            process_event(
                "xxx",
                "",
                "",
                {"event": "E" * 300, "properties": {"price": 299.99, "name": "AirPods Pro"},},
                self.team.pk,
                now().isoformat(),
                now().isoformat(),
            )
            event = get_events()[0]
            self.assertEqual(len(event.event), 200)

    return TestProcessEvent


class TestProcessEvent(test_process_event_factory(_process_event, Event.objects.all, SessionRecordingEvent.objects.all, get_elements)):  # type: ignore
    pass
