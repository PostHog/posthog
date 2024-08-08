from datetime import datetime, timedelta, UTC
from django.core.cache import cache
from flaky import flaky
from rest_framework import status

from ee.api.test.base import APILicensedTest
from dateutil import parser
from posthog.constants import ExperimentSignificanceCode
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag, get_feature_flags_for_team_in_cache
from posthog.test.base import (
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_insert_cohortpeople_queries,
    snapshot_clickhouse_queries,
    FuzzyInt,
)
from posthog.test.test_journeys import journeys_for


class TestExperimentCRUD(APILicensedTest):
    # List experiments
    def test_can_list_experiments(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_experiments_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={
                "name": "Test Experiment",
                "feature_flag_key": f"flag_0",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        ).json()

        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={
                "name": "Test Experiment",
                "feature_flag_key": f"exp_flag_000",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "end_date": "2021-12-01T10:23",
                "archived": True,
                "parameters": None,
            },
            format="json",
        ).json()

        with self.assertNumQueries(FuzzyInt(8, 9)):
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 5):
            self.client.post(
                f"/api/projects/{self.team.id}/experiments/",
                data={
                    "name": "Test Experiment",
                    "feature_flag_key": f"flag_{i}",
                    "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                    "start_date": "2021-12-01T10:23",
                    "parameters": None,
                },
                format="json",
            ).json()

        with self.assertNumQueries(FuzzyInt(8, 9)):
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_creating_updating_basic_experiment(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]
        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "end_date": end_date},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

    def test_adding_behavioral_cohort_filter_to_experiment_fails(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                    ],
                }
            },
            name="cohort_behavioral",
        )
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"filters": {"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(
            response.json()["detail"],
            "Experiments do not support global filter properties",
        )

    def test_invalid_create(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": None,  # invalid
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},  # also invalid
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "None",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},  # still invalid
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Filters are required to create an Experiment")

    def test_invalid_update(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {},
                "feature_flag_key": "new_key",
            },  # invalid
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update keys: get_feature_flag_key on Experiment",
        )

    def test_cant_reuse_existing_feature_flag(self):
        ff_key = "a-b-test"
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key=ff_key,
            created_by=self.user,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {"events": []},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "There is already a feature flag with this key.")

    def test_draft_experiment_doesnt_have_FF_active(self):
        # Draft experiment
        ff_key = "a-b-tests"
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

    def test_draft_experiment_doesnt_have_FF_active_even_after_updates(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "filters": {}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)  # didn't change to enabled while still draft

        # Now launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertTrue(created_ff.active)

    def test_launching_draft_experiment_activates_FF(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertTrue(updated_ff.active)

    def test_create_multivariate_experiment_can_update_variants_in_draft(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, False)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertTrue(experiment.is_draft)
        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 24,
                        },
                        {
                            "key": "test_3",
                            "name": "Test Variant",
                            "rollout_percentage": 10,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, False)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][3]["key"], "test_3")

    def test_create_multivariate_experiment(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertFalse(experiment.is_draft)
        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {"feature_flag_variants": [{"key": "control", "name": "X", "rollout_percentage": 33}]},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update feature_flag_variants on Experiment",
        )

        # Allow changing FF rollout %s
        created_ff = FeatureFlag.objects.get(key=ff_key)
        created_ff.filters = {
            **created_ff.filters,
            "multivariate": {
                "variants": [
                    {
                        "key": "control",
                        "name": "Control Group",
                        "rollout_percentage": 35,
                    },
                    {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                    {"key": "test_2", "name": "Test Variant", "rollout_percentage": 32},
                ]
            },
        }
        created_ff.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga 222",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["parameters"]["feature_flag_variants"][0]["key"], "control")
        self.assertEqual(response.json()["description"], "Bazinga 222")
        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["rollout_percentage"], 35)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["rollout_percentage"], 33)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["rollout_percentage"], 32)

        # Now try changing FF keys
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update feature_flag_variants on Experiment",
        )

        # Now try updating other parameter keys
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "parameters": {"recommended_sample_size": 1500}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["parameters"]["recommended_sample_size"], 1500)

    def test_creating_invalid_multivariate_experiment_no_control(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        # no control
                        {
                            "key": "test_0",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Feature flag variants must contain a control variant",
        )

    def test_deleting_experiment_soft_deletes_feature_flag(self):
        ff_key = "a-b-tests"
        data = {
            "name": "Test Experiment",
            "description": "",
            "start_date": "2021-12-01T10:23",
            "end_date": None,
            "feature_flag_key": ff_key,
            "parameters": None,
            "filters": {
                "events": [
                    {"order": 0, "id": "$pageview"},
                    {"order": 1, "id": "$pageleave"},
                ],
                "properties": [],
            },
        }
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        id = response.json()["id"]

        # Now delete the experiment
        response = self.client.delete(f"/api/projects/{self.team.id}/experiments/{id}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(Experiment.DoesNotExist):
            Experiment.objects.get(pk=id)

        # soft deleted
        self.assertEqual(FeatureFlag.objects.get(pk=created_ff.id).deleted, True)

        # can recreate new experiment with same FF key
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_soft_deleting_feature_flag_does_not_delete_experiment(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        id = response.json()["id"]

        # Now delete the feature flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{created_ff.pk}/",
            {"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        feature_flag_response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{created_ff.pk}/")
        self.assertEqual(feature_flag_response.json().get("deleted"), True)

        self.assertIsNotNone(Experiment.objects.get(pk=id))

    def test_cant_add_global_properties_to_new_experiment(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": ["technology"],
                            "operator": "exact",
                            "group_type_index": 1,
                        }
                    ],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Experiments do not support global filter properties",
        )

    def test_creating_updating_experiment_with_group_aggregation(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

        id = response.json()["id"]

        # Now update group type index on filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 0,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

        # Now remove group type index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    # "aggregation_group_type_index": None, # removed key
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

    def test_creating_experiment_with_group_aggregation_parameter(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "aggregation_group_type_index": 0,
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

        id = response.json()["id"]

        # Now update group type index on filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

    def test_used_in_experiment_is_populated_correctly_for_feature_flag_list(self) -> None:
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_experiment = response.json()["id"]

        # add another random feature flag
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        # TODO: Make sure permission bool doesn't cause n + 1
        with self.assertNumQueries(12):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = response.json()

            self.assertEqual(result["count"], 2)

            self.assertCountEqual(
                [(res["key"], res["experiment_set"]) for res in result["results"]],
                [("flag_0", []), (ff_key, [created_experiment])],
            )

    def test_create_experiment_updates_feature_flag_cache(self):
        cache.clear()

        initial_cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        self.assertIsNone(initial_cached_flags)

        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        # save was called, but no flags saved because experiment is in draft mode, so flag is not active
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(0, len(cached_flags))

        id = response.json()["id"]

        # launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "start_date": "2021-12-01T10:23",
            },
        )

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "aggregation_group_type_index": None,
            },
        )

        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {"feature_flag_variants": [{"key": "control", "name": "X", "rollout_percentage": 33}]},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update feature_flag_variants on Experiment",
        )

        # ensure cache doesn't change either
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "aggregation_group_type_index": None,
            },
        )

        # Now try changing FF rollout %s
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 34,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 32,
                        },
                    ]
                },
            },
        )
        # changing variants isn't really supported by experiments anymore, need to do it directly
        # on the FF
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # ensure cache doesn't change either
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "aggregation_group_type_index": None,
            },
        )


class TestExperimentAuxiliaryEndpoints(ClickhouseTestMixin, APILicensedTest):
    def _generate_experiment(self, start_date="2024-01-01T10:23", extra_parameters=None):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": start_date,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ],
                    **(extra_parameters or {}),
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        return response

    def test_create_exposure_cohort_for_experiment(self):
        response = self._generate_experiment("2024-01-01T10:23")

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_1"},
                    },
                ],
                "personX": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test2", "$feature_flag_response": "test_1"},
                    },
                ],
                # out of time range
                "person3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2023-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                # wrong event
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2024-01-03"},
                    {"event": "$pageleave", "timestamp": "2024-01-05"},
                ],
                # doesn't have feature value set
                "person_out_of_end_date": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["person1", "person2"], sorted([res["name"] for res in response.json()["results"]]))

    def test_create_exposure_cohort_for_experiment_with_custom_event_exposure(self):
        self.maxDiff = None

        cohort_extra = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "value": "http://example.com",
                            "type": "person",
                        },
                    ],
                }
            },
            name="cohort_X",
        )
        response = self._generate_experiment(
            "2024-01-01T10:23",
            {
                "custom_exposure_filter": {
                    "events": [
                        {
                            "id": "custom_exposure_event",
                            "order": 0,
                            "entity_type": "events",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "id", "value": cohort_extra.id, "type": "cohort"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "x", "bonk": "bonk"},
                    },
                ],
                "person2": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "y", "bonk": "bonk"},
                    },
                ],
                "person2-no-bonk": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "y"},
                    },
                ],
                "person2-not-in-prop": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "yxxxx"},
                    },
                ],
                "personX": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test2", "$feature_flag_response": "test_1"},
                    },
                ],
                # out of time range
                "person3": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2023-01-02",
                        "properties": {"$current_url": "y"},
                    },
                ],
                # wrong event
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2024-01-03"},
                    {"event": "$pageleave", "timestamp": "2024-01-05"},
                ],
            },
            self.team,
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])
        self.assertEqual(
            cohort["filters"],
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "event_filters": [
                                        {"key": "bonk", "type": "event", "value": "bonk"},
                                        {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                    ],
                                    "event_type": "events",
                                    "explicit_datetime": "2024-01-01T10:23:00+00:00",
                                    "key": "custom_exposure_event",
                                    "negation": False,
                                    "type": "behavioral",
                                    "value": "performed_event",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["person1", "person2"], sorted([res["name"] for res in response.json()["results"]]))

    @snapshot_clickhouse_insert_cohortpeople_queries
    def test_create_exposure_cohort_for_experiment_with_custom_action_filters_exposure(self):
        cohort_extra = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "value": "http://example.com",
                            "type": "person",
                        },
                    ],
                }
            },
            name="cohort_X",
        )
        cohort_extra.calculate_people_ch(pending_version=1)

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "insight",
                            "type": "event",
                            "value": ["RETENTION"],
                            "operator": "exact",
                        },
                        {
                            "key": "id",
                            "value": cohort_extra.id,
                            "type": "cohort",
                        },
                    ],
                },
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "filters_count",
                            "type": "event",
                            "value": "1",
                            "operator": "gt",
                        }
                    ],
                },
                {
                    "event": "$autocapture",
                    "url": "/123",
                    "url_matching": "regex",
                },
            ],
        )
        response = self._generate_experiment(
            datetime.now() - timedelta(days=5),
            {
                "custom_exposure_filter": {
                    "actions": [
                        {
                            "id": str(action1.id),  # should support string ids
                            "order": 0,
                            "entity_type": "actions",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "id", "value": cohort_extra.id, "type": "cohort"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {"$current_url": "x", "bonk": "bonk", "filters_count": 2},
                    },
                ],
                "person2": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {
                            "$current_url": "y",
                            "bonk": "bonk",
                            "insight": "RETENTION",
                        },  # missing pageview person property
                    },
                ],
                "person2-no-bonk": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {"$current_url": "y", "filters_count": 3},
                    },
                ],
                "person2-not-in-prop": [
                    {
                        "event": "$autocapture",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {
                            "$current_url": "https://posthog.com/feedback/1234"
                        },  # can't match because clashing current_url filters
                    },
                ],
            },
            self.team,
        )
        _create_person(
            distinct_ids=["1"],
            team_id=self.team.pk,
            properties={"$pageview": "http://example.com"},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="1",
            properties={"insight": "RETENTION", "$current_url": "x", "bonk": "bonk"},
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_person(
            distinct_ids=["2"],
            team_id=self.team.pk,
            properties={"$pageview": "http://example.com"},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="2",
            properties={"insight": "RETENTION", "$current_url": "x"},
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])

        self.maxDiff = None
        target_filter = cohort["filters"]["properties"]["values"][0]["values"][0]
        self.assertEqual(
            target_filter["event_filters"],
            [
                {"key": "bonk", "type": "event", "value": "bonk"},
                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
            ],
            cohort["filters"],
        )
        self.assertEqual(
            target_filter["event_type"],
            "actions",
        )
        self.assertEqual(
            target_filter["key"],
            action1.id,
        )
        self.assertEqual(
            target_filter["type"],
            "behavioral",
        )
        self.assertEqual(
            target_filter["value"],
            "performed_event",
        )
        explicit_datetime = parser.isoparse(target_filter["explicit_datetime"])

        self.assertTrue(
            explicit_datetime <= datetime.now(UTC) - timedelta(days=5)
            and explicit_datetime >= datetime.now(UTC) - timedelta(days=5, hours=1)
        )

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["1", "person1"], sorted([res["name"] for res in response.json()["results"]]))

    def test_create_exposure_cohort_for_experiment_with_invalid_action_filters_exposure(self):
        response = self._generate_experiment(
            "2024-01-01T10:23",
            {
                "custom_exposure_filter": {
                    "actions": [
                        {
                            "id": "oogabooga",
                            "order": 0,
                            "entity_type": "actions",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid action ID")

    def test_create_exposure_cohort_for_experiment_with_draft_experiment(self):
        response = self._generate_experiment(None)

        created_experiment = response.json()["id"]

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Experiment does not have a start date")

    def test_create_exposure_cohort_for_experiment_with_existing_cohort(self):
        response = self._generate_experiment()

        created_experiment = response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # now call to make cohort again
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Experiment already has an exposure cohort")


@flaky(max_runs=10, min_passes=1)
class ClickhouseTestFunnelExperimentResults(ClickhouseTestMixin, APILicensedTest):
    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "funnels",
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        # Variant with test: Beta(2, 3) and control: Beta(3, 1) distribution
        # The variant has very low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.114, places=2)
        self.assertEqual(
            response_data["significance_code"],
            ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE,
        )
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_with_hogql_aggregation(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature/a-b-test": "test",
                            "$account_id": "person1",
                        },
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {
                            "$feature/a-b-test": "test",
                            "$account_id": "person1",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature/a-b-test": "control",
                            "$account_id": "person2",
                        },
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {
                            "$feature/a-b-test": "control",
                            "$account_id": "person2",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {
                            "$feature/a-b-test": "control",
                            "$account_id": "person3",
                        },
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {
                            "$feature/a-b-test": "control",
                            "$account_id": "person3",
                        },
                    },
                    # doesn't have feature set
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$account_id": "person_out_of_control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$account_id": "person_out_of_control"},
                    },
                    # non converter
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature/a-b-test": "test",
                            "$account_id": "person4",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {
                            "$feature/a-b-test": "test",
                            "$account_id": "person5",
                        },
                    },
                    # doesn't have any properties
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "funnels",
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "funnel_aggregate_by_hogql": "properties.$account_id",
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        # Variant with test: Beta(2, 3) and control: Beta(3, 1) distribution
        # The variant has very low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.114, places=2)
        self.assertEqual(
            response_data["significance_code"],
            ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE,
        )
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)

    def test_experiment_with_test_account_filters(self):
        self.team.test_account_filters = [
            {
                "key": "exclude",
                "type": "event",
                "value": "yes",
                "operator": "is_not_set",
            }
        ]
        self.team.save()

        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "exclude": "yes"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test", "exclude": "yes"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3_exclude": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "exclude": "yes"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control", "exclude": "yes"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "filter_test_accounts": True,
                    "insight": "funnels",
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        # Variant with test: Beta(2, 3) and control: Beta(3, 1) distribution
        # The variant has very low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.114, places=2)
        self.assertEqual(
            response_data["significance_code"],
            ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE,
        )
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)

    def test_experiment_flow_with_event_results_cached(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^

        experiment_payload = {
            "name": "Test Experiment",
            "description": "",
            "start_date": "2020-01-01T00:00",
            "end_date": "2020-01-06T00:00",
            "feature_flag_key": ff_key,
            "parameters": None,
            "filters": {
                "insight": "funnels",
                "events": [
                    {"order": 0, "id": "$pageview"},
                    {"order": 1, "id": "$pageleave"},
                ],
                "properties": [],
            },
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            experiment_payload,
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_json = response.json()
        response_data = response_json["result"]
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(response_json.pop("is_cached"), False)

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        # Variant with test: Beta(2, 3) and control: Beta(3, 1) distribution
        # The variant has very low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.114, places=2)
        self.assertEqual(
            response_data["significance_code"],
            ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE,
        )
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)

        response2 = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")

        response2_json = response2.json()

        self.assertEqual(response2_json.pop("is_cached"), True)
        self.assertEqual(response2_json["result"], response_data)

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_and_events_out_of_time_range_timezones(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-01T13:40:00",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04T13:00:00",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03T13:00:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05 13:00:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04T13:00:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05T13:00:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                # converted on the same day as end date, but offset by a few minutes.
                # experiment ended at 10 AM, UTC+1, so this person should not be included.
                "person6": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-06T09:10:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-06T09:25:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )

        self.team.timezone = "Europe/Amsterdam"  # GMT+1
        self.team.save()

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "funnels",
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        id = response.json()["id"]

        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}/",
            {
                "start_date": "2020-01-01T13:20:21.710000Z",  # date is after first event, BUT timezone is GMT+1, so should be included
                "end_date": "2020-01-06 09:00",
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        # Variant with test: Beta(2, 3) and control: Beta(3, 1) distribution
        # The variant has very low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.114, places=2)
        self.assertEqual(
            response_data["significance_code"],
            ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE,
        )
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_for_three_test_variants(self):
        journeys_for(
            {
                "person1_2": [
                    # one event having the property is sufficient, since first touch breakdown is the default
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {}},
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                ],
                "person1_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {},
                    },
                ],
                "person2_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                ],
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {}},
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person6_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                # converters with unknown flag variant set
                "person_unknown_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "unknown_1"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "unknown_1"},
                    },
                ],
                "person_unknown_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "unknown_2"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "unknown_2"},
                    },
                ],
                "person_unknown_3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "unknown_3"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "unknown_3"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant 1",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant 2",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant 3",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "filters": {
                    "insight": "funnels",
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        self.assertAlmostEqual(response_data["probability"]["test"], 0.031, places=1)
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.158, places=1)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.324, places=1)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.486, places=1)
        self.assertEqual(
            response_data["significance_code"],
            ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE,
        )
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)


@flaky(max_runs=10, min_passes=1)
class ClickhouseTestTrendExperimentResults(ClickhouseTestMixin, APILicensedTest):
    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results(self):
        self.team.test_account_filters = [
            {
                "key": "exclude",
                "type": "event",
                "value": "yes",
                "operator": "is_not_set",
            }
        ]
        self.team.save()

        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "exclude": "yes"},
                    },
                    # exposure measured via $feature_flag_called events
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                            "exclude": "yes",
                        },
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                            "exclude": "yes",
                        },
                    },
                    # 1 exposure, but more absolute counts
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control", "exclude": "yes"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "random",
                        },
                    },
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "TRENDS",
                    "events": [{"order": 0, "id": "$pageview"}],
                    "filter_test_accounts": True,
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 5)
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(5, 0.5) and control: Gamma(5, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.923, places=2)
        self.assertFalse(response_data["significant"])

    def test_experiment_flow_with_event_results_with_custom_exposure(self):
        self.team.test_account_filters = [
            {
                "key": "exclude",
                "type": "event",
                "value": "yes",
                "operator": "is_not_set",
            }
        ]
        self.team.save()

        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "exclude": "yes"},
                    },
                    # exposure measured via $feature_flag_called events
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test", "bonk": "bonk"},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test", "bonk": "bonk", "exclude": "yes"},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature/a-b-test": "control",
                            "bonk": "no-bonk",
                        },
                    },
                ],
                "person2": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control", "bonk": "bonk"},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control", "bonk": "bonk", "exclude": "yes"},
                    },
                    # 1 exposure, but more absolute counts
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control", "bonk": "bonk"},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test", "bonk": "no-bonk"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "random", "bonk": "bonk"},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test", "bonk": "no-bonk"},
                    },
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "test", "bonk": "bonk"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "custom_exposure_filter": {
                        "events": [
                            {
                                "id": "custom_exposure_event",
                                "order": 0,
                                "properties": [{"key": "bonk", "value": "bonk"}],
                            }
                        ],
                        "filter_test_accounts": True,
                    }
                },
                "filters": {
                    "insight": "TRENDS",
                    "events": [{"order": 0, "id": "$pageview"}],
                    "filter_test_accounts": True,
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 5)
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(5, 0.5) and control: Gamma(5, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.923, places=2)
        self.assertFalse(response_data["significant"])

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_with_hogql_filter(self):
        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    # exposure measured via $feature_flag_called events
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    # 1 exposure, but more absolute counts
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "hogql": "true"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control", "hogql": "true"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "hogql": "true"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "random",
                        },
                    },
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "TRENDS",
                    "events": [
                        {
                            "order": 0,
                            "id": "$pageview",
                            "properties": [
                                {
                                    "key": "properties.hogql ilike 'true'",
                                    "type": "hogql",
                                    "value": None,
                                }
                            ],
                        }
                    ],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 5)
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(5, 0.5) and control: Gamma(5, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.923, places=2)
        self.assertFalse(response_data["significant"])

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_out_of_timerange_timezone(self):
        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    # exposure measured via $feature_flag_called events
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    # 1 exposure, but more absolute counts
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "random",
                        },
                    },
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-03",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
                # slightly out of time range
                "person_t1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-01 09:00:00",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-01 08:00:00",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-01 07:00:00",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-01 06:00:00",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-01 06:00:00",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-01 08:00:00",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test",
                        },
                    },
                ],
                "person_t2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-06 15:02:00",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-06 15:02:00",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-06 16:00:00",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
            },
            self.team,
        )

        self.team.timezone = "US/Pacific"  # GMT -8
        self.team.save()

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T10:10",  # 2 PM in GMT-8 is 10 PM in GMT
                "end_date": "2020-01-06T15:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "TRENDS",
                    "events": [{"order": 0, "id": "$pageview"}],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 5)
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(5, 0.5) and control: Gamma(5, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.923, places=2)
        self.assertFalse(response_data["significant"])

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_for_three_test_variants(self):
        journeys_for(
            {
                "person1_2": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    }
                ],
                "person1_1": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_1": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                # "person1": [
                #     {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                # ],
                "person2": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person3": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person4": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview1", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant 1",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant 2",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant 3",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "$pageview1"}],
                    "properties": [],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 3)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 2)
        self.assertEqual("test_1", result[1]["breakdown_value"])

        self.assertEqual(result[2]["count"], 1)
        self.assertEqual("test_2", result[2]["breakdown_value"])

        # test missing from results, since no events
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.299, places=2)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.119, places=2)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.583, places=2)

    def test_experiment_flow_with_event_results_for_two_test_variants_with_varying_exposures(self):
        journeys_for(
            {
                "person1_2": [
                    # for count data
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                    # for exposure counting (counted as 1 only)
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test_2",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test_2",
                        },
                    },
                ],
                "person1_1": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test_1",
                        },
                    },
                ],
                "person2_1": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "test_1",
                        },
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    # 0 exposure shouldn't ideally happen, but it's possible
                ],
                "person3": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
                "person4": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview1", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview1",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-02",
                        "properties": {
                            "$feature_flag": "a-b-test",
                            "$feature_flag_response": "control",
                        },
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant 1",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant 2",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "$pageview1"}],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 3)
        self.assertEqual("test_1", result[1]["breakdown_value"])

        self.assertEqual(result[2]["count"], 2)
        self.assertEqual("test_2", result[2]["breakdown_value"])

        # control: Gamma(4, 1)
        # test1: Gamma(3, 1)
        # test2: Gamma(2, 0.5)
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.177, places=2)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.488, places=2)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.334, places=2)

    def test_experiment_flow_with_avg_count_per_user_event_results(self):
        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "TRENDS",
                    "events": [
                        {
                            "order": 0,
                            "id": "$pageview",
                            "math": "avg_count_per_actor",
                            "name": "$pageview",
                        }
                    ],
                    "properties": [],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["data"], [0.0, 0.0, 1.0, 1.0, 1.0, 0.0])
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["data"], [0.0, 5.0, 0.0, 0.0, 2.0, 0.0])
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(7, 1) and control: Gamma(4, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.805, places=2)
        self.assertFalse(response_data["significant"])

    def test_experiment_flow_with_avg_count_per_property_value_results(self):
        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 3},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 3},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 100},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control", "mathable": 1},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "mathable": 2},
                    },
                ],
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1.5},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "TRENDS",
                    "events": [
                        {
                            "order": 0,
                            "id": "$pageview",
                            "math": "max",
                            "math_property": "mathable",
                        }
                    ],
                    "properties": [],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["data"], [0.0, 0.0, 1.0, 2.0, 1.0, 0.0])
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["data"], [0.0, 100.0, 0.0, 0.0, 1.5, 0.0])
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(7, 1) and control: Gamma(4, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.805, places=2)
        self.assertFalse(response_data["significant"])

    def test_experiment_flow_with_sum_count_per_property_value_results(self):
        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 3},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 3},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 10},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control", "mathable": 1},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control", "mathable": 2},
                    },
                ],
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "test", "mathable": 1.5},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "custom_exposure_filter": {
                        "events": [
                            {
                                "id": "$pageview",  # exposure is total pageviews
                                "order": 0,
                            }
                        ],
                    }
                },
                "filters": {
                    "insight": "TRENDS",
                    "events": [
                        {
                            "order": 0,
                            "id": "$pageview",
                            "math": "sum",
                            "math_property": "mathable",
                        }
                    ],
                    "properties": [],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["data"], [0.0, 0.0, 1.0, 4.0, 5.0, 5.0])
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["data"], [0.0, 18.0, 18.0, 18.0, 20.5, 20.5])
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(7, 1) and control: Gamma(4, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.9513, places=2)
        self.assertFalse(response_data["significant"])
