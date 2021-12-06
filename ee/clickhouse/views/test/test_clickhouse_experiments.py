from datetime import datetime

from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.test.base import APIBaseTest


class TestExperimentCRUD(APIBaseTest):
    def test_creating_updating_basic_experiment(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="a-b-test", created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag": feature_flag.pk,
                "parameters": None,
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag"], feature_flag.pk)

        id = response.json()["id"]
        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "end_date": end_date,
                "filters": {"events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}]},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

        # TODO: figure out which params we don't want to allow updating

    def test_invalid_FF_selection(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag": 123456,
                "parameters": None,
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "does_not_exist",
                "detail": 'Invalid pk "123456" - object does not exist.',
                "attr": "feature_flag",
            },
        )


class ClickhouseTestFunnelExperimentResults(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    def test_basic_experiment(self):
        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": True},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": True},},
                ],
                # doesn't have feature set
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03",},
                    {"event": "$pageleave", "timestamp": "2020-01-05",},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-03",},
                    {"event": "$pageleave", "timestamp": "2020-01-05",},
                ],
                # non-converters with FF
                "person4": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": True},},
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
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = response_data["funnel"]

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("true", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 1)
        self.assertEqual("true", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 2)
        self.assertEqual("", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 2)
        self.assertEqual("", result[1][1]["breakdown_value"][0])

        # Variant with True: Beta(2, 3) and empty: Beta(3, 1) distribution
        # probability tells the variant has low probability of being better.
        self.assertTrue(response_data["probability"] < 0.5)
