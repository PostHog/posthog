import json
from datetime import datetime, timedelta

from django.utils.timezone import now

from ee.clickhouse.models.element import get_element_group_by_hash, get_elements, get_elements_by_group
from ee.clickhouse.models.event import get_events
from ee.clickhouse.models.person import create_person_with_distinct_id, get_person_distinct_ids, get_persons
from ee.clickhouse.process_event import process_event_ee
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.base import BaseTest
from posthog.models import Person
from posthog.models.team import Team


class ClickhouseProcessEvent(ClickhouseTestMixin, BaseTest):
    def test_capture_new_person(self) -> None:
        user = self._create_user("tim")
        team_id = self.team.pk

        with self.assertNumQueries(8):
            process_event_ee(
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

        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]

        self.assertEqual(distinct_ids, ["2"])
        events = get_events()

        self.assertEqual(events[0]["event"], "$autocapture")
        group = get_element_group_by_hash(elements_hash=events[0]["elements_hash"])
        elements = get_elements_by_group(group_id=group[0]["id"])
        self.assertEqual(elements[0]["tag_name"], "a")
        self.assertEqual(elements[0]["attr_class"], ["btn", "btn-sm"])
        self.assertEqual(elements[1]["order"], 1)
        self.assertEqual(elements[1]["text"], "💻")
        self.assertEqual(events[0]["person"], "2")

    def test_capture_no_element(self) -> None:
        user = self._create_user("tim")
        person = Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])
        create_person_with_distinct_id(team_id=self.team.pk, person_id=person.pk, distinct_ids=["asdfasdfasdf"])

        process_event_ee(
            "asdfasdfasdf",
            "",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        self.assertEqual(distinct_ids, ["asdfasdfasdf"])
        events = get_events()
        self.assertEqual(events[0]["event"], "$pageview")

    def test_capture_sent_at(self) -> None:
        self._create_user("tim")
        person = Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])
        create_person_with_distinct_id(team_id=self.team.pk, person_id=person.pk, distinct_ids=["asdfasdfasdf"])

        right_now = now()
        tomorrow = right_now + timedelta(days=1, hours=2)
        tomorrow_sent_at = right_now + timedelta(days=1, hours=2, minutes=10)

        # event sent_at 10 minutes after timestamp
        process_event_ee(
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

        events = get_events()
        returned_time = datetime.strptime(events[0]["timestamp"], "%Y-%m-%dT%H:%M:%S.%f%z")
        event_seconds_before_now = (right_now - returned_time).seconds

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
        process_event_ee(
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

        events = get_events()
        returned_time = datetime.strptime(events[0]["timestamp"], "%Y-%m-%dT%H:%M:%S.%f%z")

        event_seconds_before_now = (right_now - returned_time).seconds

        # assert that the event is actually recorded 10 minutes before now
        self.assertGreater(event_seconds_before_now, 590)
        self.assertLess(event_seconds_before_now, 610)

    def test_capture_no_sent_at(self) -> None:
        self._create_user("james")
        Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

        right_now = now()
        tomorrow = right_now + timedelta(days=1, hours=2)

        # event sent_at 10 minutes after timestamp
        process_event_ee(
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

        events = get_events()
        returned_time = datetime.strptime(events[0]["timestamp"], "%Y-%m-%dT%H:%M:%S.%f%z")

        difference = abs((tomorrow - returned_time).seconds)

        self.assertLess(difference, 1)

    def test_ip_capture(self) -> None:
        user = self._create_user("tim")
        Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

        process_event_ee(
            "asdfasdfasdf",
            "11.12.13.14",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

        events = get_events()
        self.assertEqual(events[0]["properties"]["$ip"], "11.12.13.14")

    def test_anonymized_ip_capture(self) -> None:
        self.team.anonymize_ips = True
        self.team.save()

        user = self._create_user("tim")
        Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

        process_event_ee(
            "asdfasdfasdf",
            "11.12.13.14",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

        events = get_events()
        self.assertNotIn("$ip", events[0]["properties"].keys())

    def test_alias(self) -> None:
        person = Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])
        create_person_with_distinct_id(team_id=self.team.pk, person_id=person.pk, distinct_ids=["old_distinct_id"])

        process_event_ee(
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

        events = get_events()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]

        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

    def test_alias_reverse(self) -> None:
        person = Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])
        create_person_with_distinct_id(team_id=self.team.pk, person_id=person.pk, distinct_ids=["old_distinct_id"])

        process_event_ee(
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

        events = get_events()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]

        self.assertEqual(len(events), 1)
        self.assertListEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

    def test_alias_twice(self) -> None:
        person1 = Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])
        create_person_with_distinct_id(team_id=self.team.pk, person_id=person1.pk, distinct_ids=["old_distinct_id"])

        process_event_ee(
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

        person2 = Person.objects.create(team=self.team, distinct_ids=["old_distinct_id_2"])
        create_person_with_distinct_id(team_id=self.team.pk, person_id=person2.pk, distinct_ids=["old_distinct_id_2"])

        process_event_ee(
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

        distinct_ids = distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        events = get_events()

        self.assertEqual(len(events), 2)
        self.assertEqual(
            sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id", "old_distinct_id_2"]),
        )

    def test_alias_before_person(self) -> None:
        process_event_ee(
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

        events = get_events()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]

        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["new_distinct_id", "old_distinct_id"]))

    def test_alias_both_existing(self) -> None:
        person = Person.objects.create(team=self.team, distinct_ids=["old_distinct_id"])
        create_person_with_distinct_id(person_id=person.pk, distinct_ids=["old_distinct_id"], team_id=self.team.pk)
        person2 = Person.objects.create(team=self.team, distinct_ids=["new_distinct_id"])
        create_person_with_distinct_id(person_id=person2.pk, distinct_ids=["new_distinct_id"], team_id=self.team.pk)

        process_event_ee(
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

        events = get_events()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]

        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

    def test_offset_timestamp(self) -> None:
        process_event_ee(
            "distinct_id",
            "",
            "",
            {"offset": 150, "event": "$autocapture", "distinct_id": "distinct_id",},
            self.team.pk,
            "2020-01-01T12:00:05.200Z",
            "2020-01-01T12:00:05.200Z",
        )  # sent at makes no difference for offset

        events = get_events()
        returned_time = datetime.strptime(events[0]["timestamp"], "%Y-%m-%dT%H:%M:%S.%f%z")
        self.assertEqual(returned_time.isoformat(), "2020-01-01T12:00:05.050000+00:00")

    def test_offset_timestamp_no_sent_at(self) -> None:
        process_event_ee(
            "distinct_id",
            "",
            "",
            {"offset": 150, "event": "$autocapture", "distinct_id": "distinct_id",},
            self.team.pk,
            "2020-01-01T12:00:05.200Z",
            None,
        )  # no sent at makes no difference for offset

        events = get_events()
        returned_time = datetime.strptime(events[0]["timestamp"], "%Y-%m-%dT%H:%M:%S.%f%z")
        self.assertEqual(returned_time.isoformat(), "2020-01-01T12:00:05.050000+00:00")

    def test_alias_merge_properties(self) -> None:
        person1 = Person.objects.create(
            team=self.team,
            distinct_ids=["old_distinct_id"],
            properties={"key_on_both": "old value both", "key_on_old": "old value"},
        )

        create_person_with_distinct_id(
            person_id=person1.pk,
            distinct_ids=["old_distinct_id"],
            team_id=self.team.pk,
            properties={"key_on_both": "old value both", "key_on_old": "old value"},
        )

        person2 = Person.objects.create(
            team=self.team,
            distinct_ids=["new_distinct_id"],
            properties={"key_on_both": "new value both", "key_on_new": "new value"},
        )

        create_person_with_distinct_id(
            person_id=person2.pk,
            distinct_ids=["new_distinct_id"],
            team_id=self.team.pk,
            properties={"key_on_both": "new value both", "key_on_new": "new value"},
        )

        process_event_ee(
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

        events = get_events()
        self.assertEqual(len(events), 1)

        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        self.assertEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

        persons = get_persons()
        self.assertEqual(
            json.loads(persons[0]["properties"]),
            {"key_on_both": "new value both", "key_on_new": "new value", "key_on_old": "old value",},
        )

    def test_long_htext(self) -> None:
        process_event_ee(
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

        elements = get_elements()

        self.assertEqual(len(elements[0]["href"]), 2048)
        self.assertEqual(len(elements[0]["text"]), 400)


class TestIdentify(ClickhouseTestMixin, BaseTest):
    def test_distinct_with_anonymous_id(self) -> None:
        person = Person.objects.create(team=self.team, distinct_ids=["anonymous_id"])
        create_person_with_distinct_id(person_id=person.pk, team_id=self.team.pk, distinct_ids=["anonymous_id"])

        process_event_ee(
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

        events = get_events()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id"]))

        # check no errors as this call can happen multiple times
        process_event_ee(
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
        person1 = Person.objects.create(team=self.team, distinct_ids=["anonymous_id"])
        person2 = Person.objects.create(
            team=self.team, distinct_ids=["new_distinct_id"], properties={"email": "someone@gmail.com"},
        )

        create_person_with_distinct_id(person_id=person1.pk, team_id=self.team.pk, distinct_ids=["anonymous_id"])
        create_person_with_distinct_id(person_id=person2.pk, team_id=self.team.pk, distinct_ids=["new_distinct_id"])

        process_event_ee(
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

        # self.assertEqual(Event.objects.count(), 0)
        person = Person.objects.get()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id"]))
        self.assertEqual(person.properties["email"], "someone@gmail.com")

    def test_distinct_with_multiple_anonymous_ids_which_were_already_created(self,) -> None:
        # logging in the first time
        person1 = Person.objects.create(team=self.team, distinct_ids=["anonymous_id"])
        person2 = Person.objects.create(
            team=self.team, distinct_ids=["new_distinct_id"], properties={"email": "someone@gmail.com"},
        )

        create_person_with_distinct_id(person_id=person1.pk, team_id=self.team.pk, distinct_ids=["anonymous_id"])
        create_person_with_distinct_id(person_id=person2.pk, team_id=self.team.pk, distinct_ids=["new_distinct_id"])

        process_event_ee(
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

        # self.assertEqual(Event.objects.count(), 0)
        person = Person.objects.get()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id"]))
        self.assertEqual(person.properties["email"], "someone@gmail.com")

        # logging in another time

        person3 = Person.objects.create(team=self.team, distinct_ids=["anonymous_id_2"])
        create_person_with_distinct_id(person_id=person3.pk, team_id=self.team.pk, distinct_ids=["anonymous_id_2"])

        process_event_ee(
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
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids()]
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id", "anonymous_id_2"]))
        self.assertEqual(person.properties["email"], "someone@gmail.com")

    def test_distinct_team_leakage(self) -> None:
        team2 = Team.objects.create()
        person1 = Person.objects.create(team=team2, distinct_ids=["2"], properties={"email": "team2@gmail.com"})
        person2 = Person.objects.create(team=self.team, distinct_ids=["1", "2"])

        create_person_with_distinct_id(person_id=person1.pk, team_id=team2.pk, distinct_ids=["2"])

        create_person_with_distinct_id(person_id=person2.pk, team_id=self.team.pk, distinct_ids=["1", "2"])

        try:
            process_event_ee(
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

        ids = {self.team.pk: [], team2.pk: []}
        for pid in get_person_distinct_ids():
            ids[pid["team_id"]].append(pid["distinct_id"])

        self.assertEqual(sorted(ids[self.team.pk]), sorted(["1", "2"]))
        self.assertEqual(ids[team2.pk], ["2"])

        self.assertEqual(people.count(), 2)
        self.assertEqual(people[1].team, self.team)
        self.assertEqual(people[1].properties, {})
        self.assertEqual(people[1].distinct_ids, ["1", "2"])
        self.assertEqual(people[0].team, team2)
        self.assertEqual(people[0].distinct_ids, ["2"])

    def test_set_is_identified(self) -> None:
        distinct_id = "777"
        person_before_event = Person.objects.create(team=self.team, distinct_ids=[distinct_id])
        create_person_with_distinct_id(
            person_id=person_before_event.pk, team_id=self.team.pk, distinct_ids=[distinct_id]
        )

        self.assertFalse(person_before_event.is_identified)
        process_event_ee(
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
