import json
from datetime import datetime, timedelta
from typing import Any, Dict

from django.utils.timezone import now

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.event import get_events
from ee.clickhouse.models.person import get_person_by_distinct_id, get_person_distinct_ids, get_persons
from ee.clickhouse.process_event import process_event_ee
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.base import BaseTest
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.tasks.process_event import process_event


class ClickhouseProcessEvent(ClickhouseTestMixin, BaseTest):
    def test_capture_new_person(self) -> None:
        user = self._create_user("tim")
        team_id = self.team.pk

        # TODO: with self.assertNumQueries(7):

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

        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]

        self.assertEqual(distinct_ids, ["2"])
        events = get_events()

        self.assertEqual(events[0]["event"], "$autocapture")
        elements = events[0]["elements"]
        self.assertEqual(elements[0]["tag_name"], "a")
        self.assertEqual(elements[0]["attr_class"], ["btn", "btn-sm"])
        self.assertEqual(elements[1]["order"], 1)
        self.assertEqual(elements[1]["text"], "💻")
        self.assertEqual(events[0]["person"], "2")

    def test_capture_no_element(self) -> None:
        user = self._create_user("tim")
        Person.objects.create(team_id=self.team.pk, distinct_ids=["asdfasdfasdf"])

        process_event(
            "asdfasdfasdf",
            "",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

        process_event_ee(
            "asdfasdfasdf",
            "",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]
        self.assertEqual(distinct_ids, ["asdfasdfasdf"])
        events = get_events()
        self.assertEqual(events[0]["event"], "$pageview")

    def test_capture_sent_at(self) -> None:
        self._create_user("tim")
        Person.objects.create(team_id=self.team.pk, distinct_ids=["asdfasdfasdf"])

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
        Person.objects.create(team_id=self.team.pk, distinct_ids=["asdfasdfasdf"])

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
        Person.objects.create(team_id=self.team.pk, distinct_ids=["asdfasdfasdf"])

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
        Person.objects.create(team_id=self.team.pk, distinct_ids=["asdfasdfasdf"])

        process_event(
            "asdfasdfasdf",
            "11.12.13.14",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )
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

    def test_ip_override(self) -> None:
        user = self._create_user("tim")
        Person.objects.create(team=self.team, distinct_ids=["asdfasdfasdf"])

        process_event_ee(
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
        self.assertEqual(event["properties"]["$ip"], "1.0.0.1")

    def test_anonymized_ip_capture(self) -> None:
        self.team.anonymize_ips = True
        self.team.save()

        user = self._create_user("tim")
        Person.objects.create(team_id=self.team.pk, distinct_ids=["asdfasdfasdf"])

        process_event(
            "asdfasdfasdf",
            "11.12.13.14",
            "",
            {"event": "$pageview", "properties": {"distinct_id": "asdfasdfasdf", "token": self.team.api_token,},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )
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
        Person.objects.create(team_id=self.team.pk, distinct_ids=["old_distinct_id"])

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
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]

        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

    def test_alias_reverse(self) -> None:
        Person.objects.create(team_id=self.team.pk, distinct_ids=["old_distinct_id"])

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
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]

        self.assertEqual(len(events), 1)
        self.assertListEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

    def test_alias_twice(self) -> None:
        Person.objects.create(team_id=self.team.pk, distinct_ids=["old_distinct_id"])

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

        Person.objects.create(team_id=self.team.pk, distinct_ids=["old_distinct_id_2"])

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
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]

        events = get_events()

        self.assertEqual(len(events), 2)
        self.assertEqual(
            sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id", "old_distinct_id_2"]),
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

        person1 = get_person_by_distinct_id(team_id=self.team.pk, distinct_id="old_distinct_id")
        person2 = get_person_by_distinct_id(team_id=self.team.pk, distinct_id="new_distinct_id")

        self.assertEqual(person1, person2)

        events = get_events()
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]

        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["new_distinct_id", "old_distinct_id"]))

    def test_alias_both_existing(self) -> None:
        Person.objects.create(distinct_ids=["old_distinct_id"], team_id=self.team.pk)
        Person.objects.create(distinct_ids=["new_distinct_id"], team_id=self.team.pk)

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
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]

        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

    def test_offset_timestamp(self) -> None:
        process_event(
            "distinct_id",
            "",
            "",
            {"offset": 150, "event": "$autocapture", "distinct_id": "distinct_id",},
            self.team.pk,
            "2020-01-01T12:00:05.200Z",
            "2020-01-01T12:00:05.200Z",
        )  # sent at makes no difference for offset

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
        process_event(
            "distinct_id",
            "",
            "",
            {"offset": 150, "event": "$autocapture", "distinct_id": "distinct_id",},
            self.team.pk,
            "2020-01-01T12:00:05.200Z",
            None,
        )  # no sent at makes no difference for offset

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
        Person.objects.create(
            distinct_ids=["old_distinct_id"],
            team_id=self.team.pk,
            properties={"key_on_both": "old value both", "key_on_old": "old value"},
        )

        Person.objects.create(
            distinct_ids=["new_distinct_id"],
            team_id=self.team.pk,
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

        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]
        self.assertEqual(sorted(distinct_ids), sorted(["old_distinct_id", "new_distinct_id"]))

        # Assume that clickhouse has done replacement
        ch_client.execute("OPTIMIZE TABLE person")

        persons = get_persons(team_id=self.team.pk)
        self.assertEqual(
            persons[0]["properties"],
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

        events = get_events()

        self.assertEqual(len(events[0]["elements"][0]["href"]), 2048)
        self.assertEqual(len(events[0]["elements"][0]["text"]), 400)


class TestIdentify(ClickhouseTestMixin, BaseTest):
    def test_distinct_with_anonymous_id(self) -> None:
        Person.objects.create(team_id=self.team.pk, distinct_ids=["anonymous_id"])

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
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]
        self.assertEqual(len(events), 1)
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id"]))

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
        Person.objects.create(
            team_id=self.team.pk, distinct_ids=["anonymous_id"], properties={"email": "someone@gmail.com"}
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
        person = get_person_by_distinct_id(self.team.pk, "new_distinct_id")
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id"]))
        self.assertEqual(person["properties"]["email"], "someone@gmail.com")

    def test_distinct_with_multiple_anonymous_ids_which_were_already_created(self,) -> None:
        # logging in the first time
        Person.objects.create(team_id=self.team.pk, distinct_ids=["anonymous_id"])
        Person.objects.create(
            team_id=self.team.pk, distinct_ids=["new_distinct_id"], properties={"email": "someone@gmail.com"}
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
        person = get_person_by_distinct_id(self.team.pk, "new_distinct_id")
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id"]))
        self.assertEqual(person["properties"]["email"], "someone@gmail.com")

        # logging in another time

        Person.objects.create(team_id=self.team.pk, distinct_ids=["anonymous_id_2"])

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

        person = get_person_by_distinct_id(self.team.pk, "new_distinct_id")
        distinct_ids = [item["distinct_id"] for item in get_person_distinct_ids(team_id=self.team.pk)]
        self.assertEqual(sorted(distinct_ids), sorted(["anonymous_id", "new_distinct_id", "anonymous_id_2"]))
        self.assertEqual(person["properties"]["email"], "someone@gmail.com")

    def test_distinct_team_leakage(self) -> None:
        team2 = Team.objects.create()
        Person.objects.create(team_id=team2.pk, distinct_ids=["2"], properties={"email": "team2@gmail.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1", "2"])

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

        ids: Dict[int, Any] = {self.team.pk: [], team2.pk: []}

        for pid in get_person_distinct_ids(team_id=self.team.pk):
            ids[pid["team_id"]].append(pid["distinct_id"])

        for pid in get_person_distinct_ids(team_id=team2.pk):
            ids[pid["team_id"]].append(pid["distinct_id"])

        self.assertEqual(sorted(ids[self.team.pk]), sorted(["1", "2"]))
        self.assertEqual(ids[team2.pk], ["2"])

        # Assume that clickhouse has done replacement
        ch_client.execute("OPTIMIZE TABLE person")

        people1 = get_persons(team_id=self.team.pk)
        people2 = get_persons(team_id=team2.pk)

        self.assertEqual(len(people1), 1)
        self.assertEqual(len(people2), 1)
        self.assertEqual(people1[0]["team_id"], self.team.pk)
        self.assertEqual(people1[0]["properties"], {})
        self.assertEqual(people2[0]["team_id"], team2.pk)
        self.assertEqual(people2[0]["properties"], {"email": "team2@gmail.com"})

    def test_set_is_identified(self) -> None:
        distinct_id = "777"
        Person.objects.create(team_id=self.team.pk, distinct_ids=[distinct_id])
        person_before_event = get_person_by_distinct_id(team_id=self.team.pk, distinct_id=distinct_id)

        self.assertFalse(person_before_event["is_identified"])
        process_event(
            distinct_id,
            "",
            "",
            {"event": "$identify", "properties": {},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )
        process_event_ee(
            distinct_id,
            "",
            "",
            {"event": "$identify", "properties": {},},
            self.team.pk,
            now().isoformat(),
            now().isoformat(),
        )

        # Assume that clickhouse has done replacement
        ch_client.execute("OPTIMIZE TABLE person")

        person_after_event = get_person_by_distinct_id(team_id=self.team.pk, distinct_id=distinct_id)
        self.assertTrue(person_after_event["is_identified"])
