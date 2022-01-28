import json
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone

from ee.clickhouse.models.event import create_event
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_event import factory_test_event_api
from posthog.models import Action, ActionStep, Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def _create_person(**kwargs):
    return Person.objects.create(**kwargs)


class ClickhouseTestEventApi(
    ClickhouseTestMixin, factory_test_event_api(_create_event, _create_person, _create_action)  # type: ignore
):
    def test_live_action_events(self):
        pass

    @patch("ee.clickhouse.views.events.sync_execute")
    def test_optimize_query(self, patch_sync_execute):
        #  For ClickHouse we normally only query the last day,
        # but if a user doesn't have many events we still want to return events that are older
        patch_sync_execute.return_value = [("event", "d", "{}", timezone.now(), "d", "d", "d")]
        response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(patch_sync_execute.call_count, 2)

        patch_sync_execute.return_value = [("event", "d", "{}", timezone.now(), "d", "d", "d") for _ in range(0, 100)]
        response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        self.assertEqual(patch_sync_execute.call_count, 3)

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

        self.assertEqual(len(response["results"]), 2)
        self.assertEqual([r["event"] for r in response["results"]], ["should_be_included", "should_be_included"])

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

        self.assertEqual(len(response["results"]), 1)
        self.assertEqual([r["event"] for r in response["results"]], ["should_be_included"])

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

        self.assertEqual(len(response["results"]), 1)
        self.assertEqual([r["event"] for r in response["results"]], ["should_be_included"])
