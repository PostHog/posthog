from datetime import datetime
from typing import Any, Dict, List, Union
from uuid import uuid4

from django.test.client import Client

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.event import create_event
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=str(person.uuid))


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class ClickhouseTestFunnelExperimentResults(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    def test_single_property_breakdown(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$browser": "Chrome", "$browser_version": 95, "$feature/a-b-test": True},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$browser": "Chrome", "$browser_version": 95, "$feature/a-b-test": True},
                    },
                ],
                # doesn't have feature set
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$browser": "Safari", "$browser_version": 11},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$browser": "Safari", "$browser_version": 11},
                    },
                ],
            },
            self.team,
        )

        filter_for_experiment = {
            "insight": "FUNNELS",
            "actions": [],
            "events": [
                {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                {"id": "$pageleave", "name": "$pageleave", "type": "events", "order": 1},
            ],
            "display": "FunnelViz",
            "interval": "day",
            "properties": [],
            "funnel_viz_type": "steps",
            "exclusions": [],
            # "breakdown": "$browser",
            # "breakdown_type": "event",
            # "funnel_from_step": 0,
            # "funnel_to_step": 1,
        }

        feature_flag = FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="a-b-test", created_by=self.user,
        )

        experiment = Experiment.objects.create(
            name="Test Exp",
            team=self.team,
            filters=filter_for_experiment,
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 6),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        print(response_data)
        result = response_data["funnel"]

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 1)
        self.assertEqual("Chrome", result[0][0]["breakdown"])
        self.assertEqual("Chrome", result[0][0]["breakdown_value"])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 1)
        self.assertEqual("Chrome", result[0][1]["breakdown"])
        self.assertEqual("Chrome", result[0][1]["breakdown_value"])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 1)
        self.assertEqual("Safari", result[1][0]["breakdown"])
        self.assertEqual("Safari", result[1][0]["breakdown_value"])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 0)
        self.assertEqual("Safari", result[1][1]["breakdown"])
        self.assertEqual("Safari", result[1][1]["breakdown_value"])
