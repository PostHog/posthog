import json
from datetime import datetime
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    override_settings,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.utils import timezone

from dateutil import parser
from dateutil.relativedelta import relativedelta
from rest_framework import status

from posthog.models import Action, Element, Organization, Person, PropertyDefinition, User
from posthog.models.cohort import Cohort
from posthog.models.event.query_event_list import insight_query_with_columns
from posthog.test.test_journeys import journeys_for


class TestEvents(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "event"

    def test_filter_events(self):
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
            is_identified=True,
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
            elements=[
                Element(tag_name="button", text="something"),
                Element(tag_name="div"),
            ],
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some-random-uid",
            properties={"$ip": "8.8.8.8"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some-other-one",
            properties={"$ip": "8.8.8.8"},
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=2").json()
        assert response["results"][0]["person"] == {
            "distinct_ids": ["2"],
            "is_identified": True,
            "properties": {"email": "tim@posthog.com"},
        }
        assert response["results"][0]["elements"][0]["tag_name"] == "button"
        assert response["results"][0]["elements"][0]["order"] == 0
        assert response["results"][0]["elements"][1]["order"] == 1

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_filter_events_by_event_name(self):
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
        )
        _create_event(
            event="event_name",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
        )
        _create_event(
            event="another event",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
        )
        flush_persons_and_events()

        # Django session, PostHog user, PostHog team, PostHog org membership,
        # instance setting check, person and distinct id
        with self.assertNumQueries(10):
            response = self.client.get(f"/api/projects/{self.team.id}/events/?event=event_name").json()
            assert response["results"][0]["event"] == "event_name"

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_filter_events_by_properties(self):
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
        )
        _create_event(
            event="event_name",
            team=self.team,
            distinct_id="2",
            properties={"$browser": "Chrome"},
        )
        event2_uuid = _create_event(
            event="event_name",
            team=self.team,
            distinct_id="2",
            properties={"$browser": "Safari"},
        )
        flush_persons_and_events()

        # Django session, PostHog user, PostHog team, PostHog org membership,
        # look up if rate limit is enabled (cached after first lookup), instance
        # setting (poe, rate limit), person and distinct id
        expected_queries = 11

        with self.assertNumQueries(expected_queries):
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/?properties=%s"
                % (json.dumps([{"key": "$browser", "value": "Safari"}]))
            ).json()
        assert response["results"][0]["id"] == event2_uuid

        properties = "invalid_json"

        response = self.client.get(f"/api/projects/{self.team.id}/events/?properties={properties}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == self.validation_error_response("Properties are unparsable!", "invalid_input")

    def test_filter_events_by_precalculated_cohort(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"key": "value"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )

        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            with freeze_time("2020-01-04T13:01:01Z"):
                response = self.client.get(
                    f"/api/projects/{self.team.id}/events/?properties=%s"
                    % (json.dumps([{"key": "id", "value": cohort1.id, "type": "cohort"}]))
                ).json()

        assert len(response["results"]) == 2

    def test_filter_by_person(self):
        person = _create_person(
            properties={"email": "tim@posthog.com"},
            distinct_ids=["2", "some-random-uid"],
            team=self.team,
            immediate=True,
        )

        _create_event(
            event="random event",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
        )
        _create_event(
            event="random event",
            team=self.team,
            distinct_id="some-random-uid",
            properties={"$ip": "8.8.8.8"},
        )
        _create_event(
            event="random event",
            team=self.team,
            distinct_id="some-other-one",
            properties={"$ip": "8.8.8.8"},
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/events/?person_id={person.pk}").json()
        assert len(response["results"]) == 2
        assert response["results"][0]["elements"] == []

        response = self.client.get(f"/api/projects/{self.team.id}/events/?person_id={person.uuid}").json()
        assert len(response["results"]) == 2

    def test_filter_by_nonexisting_person(self):
        response = self.client.get(f"/api/projects/{self.team.id}/events/?person_id=5555555555")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 0

    @freeze_time("2020-01-10")
    def test_event_column_values(self):
        person1 = _create_person(
            properties={"email": "joe@posthog.com"},
            team=self.team,
            distinct_ids=["bla"],
        )
        person2 = _create_person(
            properties={"email": "bob@posthog.com"},
            team=self.team,
            distinct_ids=["blu"],
        )
        person3 = _create_person(
            properties={"email": "bill@posthog.com"},
            team=self.team,
            distinct_ids=["ble"],
        )
        _create_event(
            distinct_id="bla",
            event="random event 1",
            team=self.team,
        )
        _create_event(
            distinct_id="blu",
            event="random event 2",
            team=self.team,
            properties={"random_prop": "asdf"},
        )
        _create_event(
            distinct_id="ble",
            event="another random event",
            team=self.team,
            properties={"random_prop": "qwerty"},
        )

        team2 = Organization.objects.bootstrap(None)[2]
        _create_event(
            distinct_id="bla",
            event="random event",
            team=team2,
            properties={"random_prop": "abcd"},
        )

        flush_persons_and_events()

        # distinct_id
        response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=distinct_id&is_column=true").json()
        assert sorted(x["name"] for x in response) == sorted(["bla", "ble", "blu"])

        # event
        response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=event&is_column=true").json()
        assert sorted(x["name"] for x in response) == sorted(
            ["another random event", "random event 1", "random event 2"]
        )

        # person_id
        response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=person_id&is_column=true").json()
        assert sorted(x["name"] for x in response) == sorted([str(person3.uuid), str(person2.uuid), str(person1.uuid)])

        # Search
        response = self.client.get(
            f"/api/projects/{self.team.id}/events/values/?key=event&is_column=true&value=another"
        ).json()
        assert response == [{"name": "another random event"}]

    def test_custom_event_values(self):
        events = ["test", "new event", "another event"]
        for event in events:
            _create_event(
                distinct_id="bla",
                event=event,
                team=self.team,
                properties={
                    "random_prop": "don't include",
                    "some other prop": "with some text",
                },
            )
        response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=custom_event").json()
        assert sorted(events) == sorted(event["name"] for event in response)

    @also_test_with_materialized_columns(["random_prop"])
    @snapshot_clickhouse_queries
    def test_event_property_values(self):
        with freeze_time("2020-01-10"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={
                    "random_prop": "don't include",
                    "some other prop": "with some text",
                },
            )

        with freeze_time("2020-01-20 20:00:00"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "asdf", "some other prop": "with some text"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "asdf"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "qwerty"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": True},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": False},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": {"first_name": "Mary", "last_name": "Smith"}},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"something_else": "qwerty"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": 565},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": ["item1", "item2"]},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": ["item3"]},
            )

            team2 = Organization.objects.bootstrap(None)[2]
            _create_event(
                distinct_id="bla",
                event="random event",
                team=team2,
                properties={"random_prop": "abcd"},
            )
            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop").json()

            keys = [resp["name"].replace(" ", "") for resp in response]
            assert set(keys) == {
                "asdf",
                "qwerty",
                "565",
                "false",
                "true",
                '{"first_name":"Mary","last_name":"Smith"}',
                "item1",
                "item2",
                "item3",
            }
            assert len(response) == 9

            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=qw").json()
            assert response[0]["name"] == "qwerty"

            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=QW").json()
            assert response[0]["name"] == "qwerty"

            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=6").json()
            assert response[0]["name"] == "565"

            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=6&event_name=random event"
            ).json()
            assert response[0]["name"] == "565"

            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=6&event_name=foo&event_name=random event"
            ).json()
            assert response[0]["name"] == "565"

            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=qw&event_name=404_i_dont_exist"
            ).json()
            assert response == []

    @also_test_with_materialized_columns(["test_prop"])
    @freeze_time("2020-01-20 20:00:00")
    @snapshot_clickhouse_queries
    def test_event_property_values_without_hidden_properties(self):
        # Create events with properties first
        _create_event(
            distinct_id="bla",
            event="test event",
            team=self.team,
            properties={"test_prop": "visible_value"},
        )
        _create_event(
            distinct_id="bla",
            event="test event",
            team=self.team,
            properties={"test_prop": "hidden_value"},
        )
        _create_event(
            distinct_id="bla",
            event="test event",
            team=self.team,
            properties={"test_prop": "another_visible"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=test_prop").json()

        # When property is not hidden, all values should be returned
        keys = [resp["name"] for resp in response]
        assert "visible_value" in keys
        assert "hidden_value" in keys
        assert "another_visible" in keys
        assert len(response) == 3

    @also_test_with_materialized_columns(["hidden_prop", "visible_prop"])
    @freeze_time("2020-01-20 20:00:00")
    @snapshot_clickhouse_queries
    def test_event_property_values_with_hidden_properties(self):
        # Create events with both hidden and visible properties
        _create_event(
            distinct_id="bla",
            event="test event",
            team=self.team,
            properties={"hidden_prop": "should_not_appear", "visible_prop": "should_appear"},
        )
        _create_event(
            distinct_id="bla",
            event="test event",
            team=self.team,
            properties={"hidden_prop": "also_hidden", "visible_prop": "also_visible"},
        )

        # Try to import enterprise model, skip test if not available
        try:
            from ee.models.property_definition import EnterprisePropertyDefinition

            # Create hidden property definition - this should hide all values for this property
            EnterprisePropertyDefinition.objects.create(
                team=self.team, name="hidden_prop", type=PropertyDefinition.Type.EVENT, hidden=True
            )
        except ImportError:
            self.skipTest("Enterprise features not available")

        # Test hidden property returns no values
        hidden_response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=hidden_prop").json()
        assert len(hidden_response) == 0

        # Test visible property still returns values
        visible_response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=visible_prop").json()
        assert len(visible_response) == 2
        visible_keys = [resp["name"] for resp in visible_response]
        assert "should_appear" in visible_keys
        assert "also_visible" in visible_keys

    def test_property_values_with_property_filters(self):
        with freeze_time("2020-01-20 20:00:00"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "asdf", "filter_prop": "value1"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "qwerty", "filter_prop": "value1"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "no match", "filter_prop": "value2"},
            )

            # Test single property filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop=value1"
            ).json()
            assert {r["name"] for r in response} == {"asdf", "qwerty"}

            # Test array property filter
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop={json.dumps(['value1', 'value2'])}"
            ).json()
            assert {r["name"] for r in response} == {"asdf", "qwerty", "no match"}

            # Test multiple property filters
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "both filters", "filter_prop": "value1", "another_filter": "other1"},
            )
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop=value1&properties_another_filter=other1"
            ).json()
            assert len(response) == 1
            assert response[0]["name"] == "both filters"

    def test_property_values_with_property_filters_error_handling(self):
        with freeze_time("2020-01-20 20:00:00"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "asdf", "filter_prop": "value1"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "qwerty", "filter_prop": "value1"},
            )

            # Invalid JSON array - should be treated as a single value
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop=[value1,value2"
            ).json()
            assert len(response) == 0  # No matches because "[value1,value2" is treated as a literal string

            # Empty value
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop="
            ).json()
            assert len(response) == 0

            # Invalid JSON object - should be treated as a single value
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop={{invalid:json}}"
            ).json()
            assert len(response) == 0

            # Array with mixed types - should convert all values to strings for comparison
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop={json.dumps(['123', 'true', 'value1'])}"
            ).json()
            assert {r["name"] for r in response} == {"asdf", "qwerty"}

            # Test with non-string property values
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "123", "filter_prop": True},
            )
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/values/?key=random_prop&properties_filter_prop={json.dumps(['TRUE'])}"
            ).json()
            assert len(response) == 1  # Should match because "TRUE".lower() == "true"
            assert response[0]["name"] == "123"  # The value should be preserved as a string

    def test_before_and_after(self):
        user = self._create_user("tim")
        self.client.force_login(user)
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
        )

        with freeze_time("2020-01-10"):
            event1_uuid = _create_event(team=self.team, event="sign up", distinct_id="2")
        with freeze_time("2020-01-8"):
            event2_uuid = _create_event(team=self.team, event="sign up", distinct_id="2")
        with freeze_time("2020-01-7"):
            event3_uuid = _create_event(team=self.team, event="random other event", distinct_id="2")

        # with relative values
        with freeze_time("2020-01-11T12:03:03.829294Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/events/?after=4d&before=1d").json()
            assert len(response["results"]) == 2

            response = self.client.get(f"/api/projects/{self.team.id}/events/?after=6d&before=2h").json()
            assert len(response["results"]) == 3

            response = self.client.get(f"/api/projects/{self.team.id}/events/?before=4d").json()
            assert len(response["results"]) == 1

        action = Action.objects.create(team=self.team, steps_json=[{"event": "sign up"}])

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?after=2020-01-09T00:00:00.000Z&action_id=%s" % action.pk
        ).json()
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == event1_uuid

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?before=2020-01-09T00:00:00.000Z&action_id=%s" % action.pk
        ).json()
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == event2_uuid

        # without action
        response = self.client.get(f"/api/projects/{self.team.id}/events/?after=2020-01-09T00:00:00.000Z").json()
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] == event1_uuid

        response = self.client.get(f"/api/projects/{self.team.id}/events/?before=2020-01-09T00:00:00.000Z").json()
        assert len(response["results"]) == 2
        assert response["results"][0]["id"] == event2_uuid
        assert response["results"][1]["id"] == event3_uuid

    def test_pagination(self):
        with freeze_time("2021-10-10T12:03:03.829294Z"):
            _create_person(team=self.team, distinct_ids=["1"])
            for idx in range(0, 250):
                _create_event(
                    team=self.team,
                    event="some event",
                    distinct_id="1",
                    timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
                )
            response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=1").json()
            assert len(response["results"]) == 100
            assert f"http://testserver/api/projects/{self.team.id}/events/?distinct_id=1&before=" in unquote(
                response["next"]
            )
            response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=1").json()
            assert len(response["results"]) == 100
            assert f"http://testserver/api/projects/{self.team.id}/events/?distinct_id=1&before=" in unquote(
                response["next"]
            )

            page2 = self.client.get(response["next"]).json()

            from posthog.clickhouse.client import sync_execute

            assert (
                sync_execute(
                    "select count(*) from events where team_id = %(team_id)s",
                    {"team_id": self.team.pk},
                )[0][0]
                == 250
            )

            assert len(page2["results"]) == 100
            assert (
                unquote(page2["next"])
                == f"http://testserver/api/projects/{self.team.id}/events/?distinct_id=1&before=2020-12-30T12:03:53.829294+00:00"
            )

            page3 = self.client.get(page2["next"]).json()
            assert len(page3["results"]) == 50
            assert page3["next"] is None

    def test_pagination_bounded_date_range(self):
        with freeze_time("2021-10-10T12:03:03.829294Z"):
            _create_person(team=self.team, distinct_ids=["1"])
            now = timezone.now() - relativedelta(months=11)
            after = (now).astimezone(ZoneInfo("UTC")).isoformat()
            before = (now + relativedelta(days=23)).astimezone(ZoneInfo("UTC")).isoformat()
            params = {"distinct_id": "1", "after": after, "before": before, "limit": 10}
            params_string = urlencode(params)
            for idx in range(0, 25):
                _create_event(
                    team=self.team,
                    event="some event",
                    distinct_id="1",
                    timestamp=now + relativedelta(days=idx, seconds=-idx),
                )
            response = self.client.get(f"/api/projects/{self.team.id}/events/?{params_string}").json()
            assert len(response["results"]) == 10
            assert "before=" in unquote(response["next"])
            assert f"after={after}" in unquote(response["next"])

            params = {"distinct_id": "1", "after": after, "before": before, "limit": 10}
            params_string = urlencode(params)

            response = self.client.get(f"/api/projects/{self.team.id}/events/?{params_string}").json()
            assert len(response["results"]) == 10
            assert "before=" in unquote(response["next"])
            assert f"after={after}" in unquote(response["next"])

            page2 = self.client.get(response["next"]).json()

            from posthog.clickhouse.client import sync_execute

            assert (
                sync_execute(
                    "select count(*) from events where team_id = %(team_id)s",
                    {"team_id": self.team.pk},
                )[0][0]
                == 25
            )

            assert len(page2["results"]) == 10
            assert "before=" in unquote(page2["next"])
            assert f"after={after}" in unquote(page2["next"])

            page3 = self.client.get(page2["next"]).json()
            assert len(page3["results"]) == 3
            assert page3["next"] is None

    def test_ascending_order_timestamp(self):
        for idx in range(20):
            _create_event(
                team=self.team,
                event="some event",
                distinct_id="1",
                timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?distinct_id=1&limit=10&orderBy={json.dumps(['timestamp'])}"
        ).json()
        assert len(response["results"]) == 10
        assert parser.parse(response["results"][0]["timestamp"]) < parser.parse(response["results"][-1]["timestamp"])
        assert "after=" in response["next"]

    def test_default_descending_order_timestamp(self):
        for idx in range(20):
            _create_event(
                team=self.team,
                event="some event",
                distinct_id="1",
                timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
            )

        response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=1&limit=10").json()
        assert len(response["results"]) == 10
        assert parser.parse(response["results"][0]["timestamp"]) > parser.parse(response["results"][-1]["timestamp"])
        assert "before=" in response["next"]

    def test_specified_descending_order_timestamp(self):
        for idx in range(20):
            _create_event(
                team=self.team,
                event="some event",
                distinct_id="1",
                timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?distinct_id=1&limit=10&orderBy={json.dumps(['-timestamp'])}"
        ).json()
        assert len(response["results"]) == 10
        assert parser.parse(response["results"][0]["timestamp"]) > parser.parse(response["results"][-1]["timestamp"])
        assert "before=" in response["next"]

    def test_action_no_steps(self):
        action = Action.objects.create(team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/events/?action_id=%s" % action.pk)
        assert response.status_code == 200
        assert len(response.json()["results"]) == 0

    def test_get_single_action(self):
        event1_uuid = _create_event(
            team=self.team,
            event="sign up",
            distinct_id="2",
            properties={"key": "test_val"},
        )
        response = self.client.get(f"/api/projects/{self.team.id}/events/%s/" % event1_uuid)
        assert response.status_code == 200
        assert response.json()["event"] == "sign up"
        assert response.json()["properties"] == {"key": "test_val"}

    def test_events_in_future(self):
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(
                team=self.team,
                event="5th action",
                distinct_id="2",
                properties={"$os": "Windows 95"},
            )
        # Don't show events more than 5 seconds in the future
        with freeze_time("2012-01-15T04:01:44.000Z"):
            _create_event(
                team=self.team,
                event="5th action",
                distinct_id="2",
                properties={"$os": "Windows 95"},
            )
        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        assert len(response["results"]) == 1

    def test_get_event_by_id(self):
        _create_person(
            properties={"email": "someone@posthog.com"},
            team=self.team,
            distinct_ids=["1"],
            is_identified=True,
        )
        event_id = _create_event(team=self.team, event="event", distinct_id="1", timestamp=timezone.now())

        response = self.client.get(f"/api/projects/{self.team.id}/events/{event_id}")
        assert response.status_code == status.HTTP_200_OK
        response_json = response.json()
        assert response_json["event"] == "event"
        assert response_json["person"] is None

        with_person_response = self.client.get(f"/api/projects/{self.team.id}/events/{event_id}?include_person=true")
        assert with_person_response.status_code == status.HTTP_200_OK
        with_person_response_json = with_person_response.json()
        assert with_person_response_json["event"] == "event"
        assert with_person_response_json["person"] is not None

        response = self.client.get(f"/api/projects/{self.team.id}/events/123456")
        # EE will inform the user the ID passed is not a valid UUID
        assert response.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST]

        response = self.client.get(f"/api/projects/{self.team.id}/events/im_a_string_not_an_integer")
        assert response.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST]

    def test_limit(self):
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
            is_identified=True,
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
            elements=[
                Element(tag_name="button", text="something"),
                Element(tag_name="div"),
            ],
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some-random-uid",
            properties={"$ip": "8.8.8.8"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some-other-one",
            properties={"$ip": "8.8.8.8"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/events/?limit=1").json()
        assert len(response["results"]) == 1

        response = self.client.get(f"/api/projects/{self.team.id}/events/?limit=2").json()
        assert len(response["results"]) == 2

    def test_get_events_with_specified_token(self):
        _, _, user2 = User.objects.bootstrap("Test", "team2@posthog.com", None)
        assert user2.team is not None
        assert self.team is not None

        assert user2.team.id != self.team.id

        event1_uuid = _create_event(
            team=self.team,
            event="sign up",
            distinct_id="2",
            properties={"key": "test_val"},
        )
        event2_uuid = _create_event(
            team=user2.team,
            event="sign up",
            distinct_id="2",
            properties={"key": "test_val"},
        )

        response_team1 = self.client.get(f"/api/projects/{self.team.id}/events/{event1_uuid}/")
        response_team1_token = self.client.get(
            f"/api/projects/{self.team.id}/events/{event1_uuid}/",
            data={"token": self.team.api_token},
        )

        response_team2_event1 = self.client.get(
            f"/api/projects/{self.team.id}/events/{event1_uuid}/",
            data={"token": user2.team.api_token},
        )

        # The feature being tested here is usually used with personal API token auth,
        # but logging in works the same way and is more to the point in the test
        self.client.force_login(user2)

        response_team2_event2 = self.client.get(
            f"/api/projects/{self.team.id}/events/{event2_uuid}/",
            data={"token": user2.team.api_token},
        )

        assert response_team1.status_code == status.HTTP_200_OK
        assert response_team1_token.status_code == status.HTTP_200_OK
        assert response_team1.json() == response_team1_token.json()
        assert response_team1.json() != response_team2_event2.json()
        assert response_team2_event1.status_code == status.HTTP_403_FORBIDDEN
        assert response_team2_event2.status_code == status.HTTP_200_OK

        response_invalid_token = self.client.get(f"/api/projects/{self.team.id}/events?token=invalid")
        assert response_invalid_token.status_code == 401

    @patch("posthog.models.event.query_event_list.insight_query_with_columns")
    def test_optimize_query(self, patch_query_with_columns):
        # For ClickHouse we normally only query the last day,
        # but if a user doesn't have many events we still want to return events that are older
        patch_query_with_columns.return_value = [
            {
                "uuid": "event",
                "event": "d",
                "properties": "{}",
                "timestamp": timezone.now(),
                "team_id": "d",
                "distinct_id": "d",
                "elements_chain": "d",
            }
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        assert len(response["results"]) == 1
        assert patch_query_with_columns.call_count == 2

        patch_query_with_columns.return_value = [
            {
                "uuid": "event",
                "event": "d",
                "properties": "{}",
                "timestamp": timezone.now(),
                "team_id": "d",
                "distinct_id": "d",
                "elements_chain": "d",
            }
            for _ in range(0, 100)
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        assert patch_query_with_columns.call_count == 3

    @patch("posthog.models.event.query_event_list.insight_query_with_columns", wraps=insight_query_with_columns)
    def test_optimize_query_with_bounded_dates(self, patch_query_with_columns):
        # For ClickHouse we normally only query the last day,
        # but if a user doesn't have many events we still want to return events that are older

        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="2",
            timestamp=datetime(2024, 1, 1, 1, 0, 0, 12345),
            properties={"key": "test_val"},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?after=2021-01-01&before=2024-01-01T02:02:02Z"
        ).json()
        assert len(response["results"]) == 1
        assert patch_query_with_columns.call_count == 2

        [
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                timestamp=datetime(2024, 1, 1, 1, 2, round(_ / 2), _),
                properties={"key": "test_val"},
            )
            for _ in range(0, 100)
        ]
        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?after=2023-01-01T01:01:00Z&before=2024-01-01T02:02:01Z"
        ).json()
        assert patch_query_with_columns.call_count == 3
        assert len(response["results"]) == 100

        # Test for the bug where we wouldn't respect ?after if we had more 100 results on the same day
        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?after=2024-01-01T01:02:00Z&before=2024-01-01T01:04:01Z"
        ).json()
        assert len(response["results"]) == 99
        assert patch_query_with_columns.call_count == 5
        assert response["next"] is None

    def test_filter_events_by_being_after_properties_with_date_type(self):
        journeys_for(
            {
                "2": [
                    {
                        "event": "should_be_excluded",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 18).timestamp()},
                    },
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 19).timestamp()},
                    },
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 20).timestamp()},
                    },
                ]
            },
            self.team,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?properties=%s"
            % (
                json.dumps(
                    [
                        {
                            "key": "prop_that_is_a_unix_timestamp",
                            "value": "2012-01-07 18:30:00",
                            "operator": "is_date_after",
                            "type": "event",
                        }
                    ]
                )
            )
        ).json()

        assert [r["event"] for r in response["results"]] == ["should_be_included", "should_be_included"]

    def test_filter_events_by_being_before_properties_with_date_type(self):
        journeys_for(
            {
                "2": [
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 18).timestamp()},
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 19).timestamp()},
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 20).timestamp()},
                    },
                ]
            },
            self.team,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?properties=%s"
            % (
                json.dumps(
                    [
                        {
                            "key": "prop_that_is_a_unix_timestamp",
                            "value": "2012-01-07 18:30:00",
                            "operator": "is_date_before",
                            "type": "event",
                        }
                    ]
                )
            )
        ).json()

        assert [r["event"] for r in response["results"]] == ["should_be_included"]

    def test_filter_events_with_date_format(self):
        journeys_for(
            {
                "2": [
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_an_sdk_style_unix_timestamp": 1639427152.339},
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {
                            "prop_that_is_an_sdk_style_unix_timestamp": 1639427152.339 * 2
                        },  # the far future
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {
                            "prop_that_is_an_sdk_style_unix_timestamp": 1639427152.339 * 2
                        },  # the far future
                    },
                ]
            },
            self.team,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?properties=%s"
            % (
                json.dumps(
                    [
                        {
                            "key": "prop_that_is_an_sdk_style_unix_timestamp",
                            "value": "2021-12-25 12:00:00",
                            "operator": "is_date_before",
                            "type": "event",
                            "property_type": "DateTime",
                            "property_type_format": "unix_timestamp",
                        }
                    ]
                )
            )
        ).json()

        assert [r["event"] for r in response["results"]] == ["should_be_included"]
