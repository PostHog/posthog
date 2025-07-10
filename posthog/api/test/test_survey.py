import re
from datetime import datetime, timedelta, UTC
from typing import Any
from unittest.mock import ANY, patch

from django.test.client import Client
from freezegun.api import freeze_time
from rest_framework import status

from posthog.models import FeatureFlag
from posthog.models.cohort.cohort import Cohort
from posthog.models.surveys.survey import Survey, MAX_ITERATION_COUNT
from posthog.test.base import (
    APIBaseTest,
)


class TestSurvey(APIBaseTest):
    def _assert_matches_with_any(self, actual, expected):
        """Helper to compare dictionaries with ANY matchers"""
        if isinstance(expected, dict) and isinstance(actual, dict):
            for key, expected_value in expected.items():
                if key not in actual:
                    self.fail(f"Missing key: {key}")
                if expected_value is ANY:
                    continue  # Skip ANY comparisons
                elif isinstance(expected_value, dict):
                    self._assert_matches_with_any(actual[key], expected_value)
                elif isinstance(expected_value, list):
                    self.assertEqual(len(actual[key]), len(expected_value))
                    for i, item in enumerate(expected_value):
                        if isinstance(item, dict):
                            self._assert_matches_with_any(actual[key][i], item)
                        else:
                            self.assertEqual(actual[key][i], item)
                else:
                    self.assertEqual(actual[key], expected_value)
        else:
            self.assertEqual(actual, expected)

    def test_can_create_basic_survey(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What do you think of the new notebooks feature?",
                    }
                ],
                "targeting_flag_filters": None,
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["description"] == "Get feedback on the new notebooks feature"
        assert response_data["type"] == "popover"
        assert response_data["schedule"] == "once"
        assert response_data["enable_partial_responses"] is False
        assert response_data["questions"] == [
            {
                "id": str(response_data["questions"][0]["id"]),
                "type": "open",
                "question": "What do you think of the new notebooks feature?",
            }
        ]
        assert response_data["created_by"]["id"] == self.user.id

    @patch("posthog.api.feature_flag.report_user_action")
    def test_creation_context_is_set_to_surveys(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()

        # Ensure that a FeatureFlag has been created
        ff_instance = FeatureFlag.objects.get(id=response_data["internal_targeting_flag"]["id"])
        self.assertIsNotNone(ff_instance)

        # Verify that report_user_action was called for the feature flag creation
        mock_capture.assert_any_call(
            ANY,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": True,
                "filter_count": 2,
                "created_at": ff_instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
                "creation_context": "surveys",
            },
        )

    def test_create_adds_user_interactivity_filters(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What do you think of the new notebooks feature?",
                    }
                ],
                "targeting_flag_filters": None,
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        survey = Survey.objects.get(id=response_data["id"])
        assert survey
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["description"] == "Get feedback on the new notebooks feature"
        assert response_data["type"] == "popover"
        assert response_data["schedule"] == "once"
        assert response_data["enable_partial_responses"] is False
        assert response_data["questions"] == [
            {
                "id": str(response_data["questions"][0]["id"]),
                "type": "open",
                "question": "What do you think of the new notebooks feature?",
            }
        ]
        assert response_data["created_by"]["id"] == self.user.id
        assert survey.internal_targeting_flag
        survey_id = response_data["id"]
        user_submitted_dismissed_filter = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$survey_dismissed/{survey_id}",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                        {
                            "key": f"$survey_responded/{survey_id}",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                }
            ]
        }

        assert survey.internal_targeting_flag.filters == user_submitted_dismissed_filter

        assert survey.internal_targeting_flag.active is False

        # launch survey
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
            },
        )
        survey = Survey.objects.get(id=response_data["id"])
        assert survey.internal_targeting_flag.active is True

    def test_can_create_survey_with_linked_flag_and_targeting(self):
        notebooks_flag = FeatureFlag.objects.create(team=self.team, key="notebooks", created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "linked_flag_id": notebooks_flag.id,
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["linked_flag"]["id"] == notebooks_flag.id
        assert FeatureFlag.objects.filter(id=response_data["targeting_flag"]["id"]).exists()
        self.assertNotEqual(response_data["targeting_flag"]["key"], "survey-targeting-power-users-survey")
        assert re.match(r"^survey-targeting-[a-z0-9]+$", response_data["targeting_flag"]["key"])
        assert response_data["schedule"] == "once"
        assert response_data["enable_partial_responses"] is False

        assert response_data["targeting_flag"]["filters"] == {
            "groups": [
                {
                    "variant": None,
                    "properties": [
                        {
                            "key": "billing_plan",
                            "value": ["cloud"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ],
                    "rollout_percentage": None,
                }
            ]
        }
        assert response_data["conditions"] == {"url": "https://app.posthog.com/notebooks"}
        assert response_data["questions"] == [
            {
                "id": str(response_data["questions"][0]["id"]),
                "type": "open",
                "question": "What would you want to improve from notebooks?",
            }
        ]

    def test_can_create_survey_with_targeting_with_remove_parameter(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "remove_targeting_flag": False,
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert FeatureFlag.objects.filter(id=response_data["targeting_flag"]["id"]).exists()
        assert response_data["targeting_flag"]["filters"] == {
            "groups": [
                {
                    "variant": None,
                    "properties": [
                        {
                            "key": "billing_plan",
                            "value": ["cloud"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ],
                    "rollout_percentage": None,
                }
            ]
        }
        assert response_data["conditions"] == {"url": "https://app.posthog.com/notebooks"}
        assert response_data["questions"] == [
            {
                "id": str(response_data["questions"][0]["id"]),
                "type": "open",
                "question": "What would you want to improve from notebooks?",
            }
        ]

    def test_used_in_survey_is_populated_correctly_for_feature_flag_list(self) -> None:
        ff_key = "notebooks"
        notebooks_flag = FeatureFlag.objects.create(team=self.team, key=ff_key, created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "linked_flag_id": notebooks_flag.id,
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["linked_flag"]["id"] == notebooks_flag.id
        assert FeatureFlag.objects.filter(id=response_data["targeting_flag"]["id"]).exists()

        created_survey1 = response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks random survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "linked_flag_id": notebooks_flag.id,
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["linked_flag"]["id"] == notebooks_flag.id
        assert response_data["targeting_flag"] is None

        created_survey2 = response.json()["id"]

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

        with self.assertNumQueries(22):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = response.json()

            self.assertEqual(result["count"], 2)

            self.assertEqual(
                [(res["key"], [survey["id"] for survey in res["surveys"]]) for res in result["results"]],
                [("flag_0", []), (ff_key, [created_survey1, created_survey2])],
            )

    def test_updating_survey_with_invalid_iteration_count_is_rejected(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                        }
                    ]
                },
                "iteration_count": MAX_ITERATION_COUNT + 1,
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        assert survey_with_targeting.status_code == status.HTTP_400_BAD_REQUEST
        assert survey_with_targeting.json() == {
            "type": "validation_error",
            "code": "max_value",
            "detail": f"Ensure this value is less than or equal to {MAX_ITERATION_COUNT}.",
            "attr": "iteration_count",
        }

    def test_updating_survey_with_invalid_targeting_throws_appropriate_error(self):
        cohort_not_valid_for_ff = Cohort.objects.create(
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
                        {"key": "email", "value": "test@posthog.com", "type": "person"},
                    ],
                }
            },
            name="cohort2",
        )
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "id",
                                    "value": cohort_not_valid_for_ff.pk,
                                    "operator": "exact",
                                    "type": "cohort",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )

        assert survey_with_targeting.status_code == status.HTTP_400_BAD_REQUEST
        assert survey_with_targeting.json() == {
            "type": "validation_error",
            "code": "behavioral_cohort_found",
            "detail": "Cohort 'cohort2' with filters on events cannot be used in surveys.",
            "attr": None,
        }

    def test_updating_survey_with_targeting_creates_or_updates_targeting_flag(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        survey_without_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey without targeting",
                "type": "popover",
            },
            format="json",
        ).json()

        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).exists()
        assert survey_without_targeting["targeting_flag"] is None

        updated_survey_creates_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_without_targeting['id']}/",
            data={
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "email",
                                    "value": ["max@posthog.com"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
            },
        )
        assert updated_survey_creates_targeting_flag.status_code == status.HTTP_200_OK
        assert updated_survey_creates_targeting_flag.json()["name"] == "survey without targeting"
        assert FeatureFlag.objects.filter(
            id=updated_survey_creates_targeting_flag.json()["targeting_flag"]["id"]
        ).exists()

        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().filters == {
            "groups": [
                {
                    "variant": None,
                    "properties": [
                        {
                            "key": "billing_plan",
                            "value": ["cloud"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ],
                    "rollout_percentage": None,
                }
            ]
        }
        updated_survey_updates_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "targeting_flag_filters": {"groups": [{"variant": None, "rollout_percentage": 20, "properties": []}]},
            },
        )
        assert updated_survey_updates_targeting_flag.status_code == status.HTTP_200_OK
        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().filters == {
            "groups": [{"variant": None, "properties": [], "rollout_percentage": 20}]
        }

    def test_updating_survey_to_send_none_targeting_doesnt_delete_targeting_flag(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        flagId = survey_with_targeting["targeting_flag"]["id"]
        assert FeatureFlag.objects.filter(id=flagId).exists()

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "name": "other",
                # "targeting_flag_filters": None, # don't delete these
            },
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_200_OK
        assert updated_survey_deletes_targeting_flag.json()["name"] == "other"
        assert updated_survey_deletes_targeting_flag.json()["targeting_flag"] is not None

        assert FeatureFlag.objects.filter(id=flagId).exists()

    def test_updating_survey_to_remove_targeting_deletes_targeting_flag(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        flagId = survey_with_targeting["targeting_flag"]["id"]
        assert FeatureFlag.objects.filter(id=flagId).exists()

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "remove_targeting_flag": True,  # delete targeting flag
            },
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_200_OK
        assert updated_survey_deletes_targeting_flag.json()["name"] == "survey with targeting"
        assert updated_survey_deletes_targeting_flag.json()["targeting_flag"] is None

        with self.assertRaises(FeatureFlag.DoesNotExist):
            FeatureFlag.objects.get(id=flagId)

        with self.assertRaises(FeatureFlag.DoesNotExist):
            FeatureFlag.objects.get(key="survey-targeting-survey-with-targeting")

    def test_updating_survey_other_props_doesnt_delete_targeting_flag(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        flagId = survey_with_targeting["targeting_flag"]["id"]
        assert FeatureFlag.objects.filter(id=flagId).exists()

        updated_survey_does_not_delete_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={"start_date": "2023-04-01T12:00:10"},
        )

        assert updated_survey_does_not_delete_targeting_flag.status_code == status.HTTP_200_OK
        assert updated_survey_does_not_delete_targeting_flag.json()["name"] == "survey with targeting"
        assert updated_survey_does_not_delete_targeting_flag.json()["targeting_flag"] is not None

        assert FeatureFlag.objects.filter(id=flagId).exists()

    def test_survey_targeting_flag_validation(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        flagId = survey_with_targeting["targeting_flag"]["id"]
        assert FeatureFlag.objects.filter(id=flagId).exists()

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [],
                        }
                    ]
                },
            },
        )

        invalid_detail = "Invalid operation: User targeting rolls out to everyone. If you want to roll out to everyone, delete this targeting"

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_400_BAD_REQUEST
        assert updated_survey_deletes_targeting_flag.json()["detail"] == invalid_detail

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": 100,
                            "properties": [{"key": "value"}],
                        },
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [],
                        },
                    ]
                },
            },
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_400_BAD_REQUEST
        assert updated_survey_deletes_targeting_flag.json()["detail"] == invalid_detail

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": 100,
                            "properties": [{"key": "value"}],
                        },
                        {
                            "variant": None,
                            "rollout_percentage": 100,
                            "properties": [],
                        },
                    ]
                },
            },
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_400_BAD_REQUEST
        assert updated_survey_deletes_targeting_flag.json()["detail"] == invalid_detail

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": 100,
                            "properties": [{"key": "value", "type": "person", "value": "bleh"}],
                        },
                        {
                            "variant": None,
                            "rollout_percentage": 30,
                            "properties": [],
                        },
                    ]
                },
            },
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_200_OK

    def test_survey_targeting_flag_numeric_validation(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with numeric targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "$browser_version",
                                    "value": "10",
                                    "operator": "gt",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": ""},
            },
            format="json",
        )
        assert survey_with_targeting.status_code == status.HTTP_201_CREATED

    def test_updating_survey_to_send_none_linked_flag_removes_linking(self):
        linked_flag = FeatureFlag.objects.create(team=self.team, key="early-access", created_by=self.user)

        survey_with_linked_flag = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "linked_flag_id": linked_flag.id,
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        flagId = survey_with_linked_flag["linked_flag"]["id"]
        assert FeatureFlag.objects.filter(id=flagId).exists()

        updated_survey_removes_linked_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_linked_flag['id']}/",
            data={
                "linked_flag_id": None,
            },
        )

        assert updated_survey_removes_linked_flag.status_code == status.HTTP_200_OK
        assert updated_survey_removes_linked_flag.json()["name"] == "survey with targeting"
        assert updated_survey_removes_linked_flag.json()["linked_flag"] is None

        assert FeatureFlag.objects.filter(id=flagId).exists()

    def test_deleting_survey_does_not_delete_linked_flag(self):
        linked_flag = FeatureFlag.objects.create(team=self.team, key="early-access", created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Early access survey",
                "type": "popover",
                "linked_flag_id": linked_flag.id,
            },
            format="json",
        )
        assert FeatureFlag.objects.filter(id=linked_flag.id).exists()

        deleted_survey = self.client.delete(
            f"/api/projects/{self.team.id}/surveys/{response.json()['id']}/",
            format="json",
        )
        assert deleted_survey.status_code == status.HTTP_204_NO_CONTENT
        assert FeatureFlag.objects.filter(id=linked_flag.id).exists()

    def test_deleting_survey_deletes_targeting_flag(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
            },
            format="json",
        )
        assert FeatureFlag.objects.filter(id=response.json()["targeting_flag"]["id"]).exists()

        deleted_survey = self.client.delete(
            f"/api/projects/{self.team.id}/surveys/{response.json()['id']}/",
            format="json",
        )
        assert deleted_survey.status_code == status.HTTP_204_NO_CONTENT
        assert not FeatureFlag.objects.filter(id=response.json()["targeting_flag"]["id"]).exists()

    def test_inactive_surveys_disables_targeting_flag(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()
        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().active is False
        # launch survey
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
            },
        )
        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().active is True
        # stop the survey
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "end_date": datetime.now() + timedelta(days=1),
            },
        )
        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().active is False
        # resume survey again
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "end_date": None,
            },
        )
        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().active is True

    def test_inactive_surveys_disables_internal_targeting_flag(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        survey = Survey.objects.get(id=survey_with_targeting["id"])
        assert survey
        assert survey.internal_targeting_flag
        assert survey.internal_targeting_flag.active is False
        # launch survey
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
            },
        )

        assert FeatureFlag.objects.filter(id=survey.internal_targeting_flag.id).get().active is True
        # stop the survey
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "end_date": datetime.now() + timedelta(days=1),
            },
        )

        assert FeatureFlag.objects.filter(id=survey.internal_targeting_flag.id).get().active is False

        # resume survey again
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "end_date": None,
            },
        )
        assert FeatureFlag.objects.filter(id=survey.internal_targeting_flag.id).get().active is True

    def test_options_unauthenticated(self):
        unauthenticated_client = Client(enforce_csrf_checks=True)
        unauthenticated_client.logout()
        request_headers = {"HTTP_ACCESS_CONTROL_REQUEST_METHOD": "GET", "HTTP_ORIGIN": "*", "USER_AGENT": "Agent 008"}
        response = unauthenticated_client.options(
            "/api/surveys", data={}, follow=False, secure=False, headers={}, **request_headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_can_list_surveys(self):
        self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "description": "Make notebooks better",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
            },
        )

        list = self.client.get(f"/api/projects/{self.team.id}/surveys/")
        response_data = list.json()
        assert list.status_code == status.HTTP_200_OK, response_data
        survey = Survey.objects.get(team_id=self.team.id)
        assert response_data == {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {
                    "id": ANY,
                    "name": "Notebooks power users survey",
                    "description": "Make notebooks better",
                    "type": "popover",
                    "schedule": "once",
                    "enable_partial_responses": False,
                    "is_publicly_shareable": None,
                    "questions": [
                        {
                            "id": response_data["results"][0]["questions"][0]["id"],
                            "type": "open",
                            "question": "What would you want to improve from notebooks?",
                        }
                    ],
                    "appearance": None,
                    "created_at": ANY,
                    "created_by": ANY,
                    "targeting_flag": None,
                    "internal_targeting_flag": {
                        "id": ANY,
                        "team_id": self.team.id,
                        "key": ANY,
                        "name": "Targeting flag for survey Notebooks power users survey",
                        "filters": {
                            "groups": [
                                {
                                    "variant": "",
                                    "properties": [
                                        {
                                            "key": f"$survey_dismissed/{survey.id}",
                                            "type": "person",
                                            "value": "is_not_set",
                                            "operator": "is_not_set",
                                        },
                                        {
                                            "key": f"$survey_responded/{survey.id}",
                                            "type": "person",
                                            "value": "is_not_set",
                                            "operator": "is_not_set",
                                        },
                                    ],
                                    "rollout_percentage": 100,
                                }
                            ]
                        },
                        "deleted": False,
                        "active": False,
                        "ensure_experience_continuity": False,
                        "has_encrypted_payloads": False,
                        "version": ANY,  # Add version field with ANY matcher
                    },
                    "linked_flag": None,
                    "linked_flag_id": None,
                    "conditions": None,
                    "archived": False,
                    "start_date": None,
                    "end_date": None,
                    "responses_limit": None,
                    "feature_flag_keys": [
                        {"key": "linked_flag_key", "value": None},
                        {"key": "targeting_flag_key", "value": None},
                        {
                            "key": "internal_targeting_flag_key",
                            "value": survey.internal_targeting_flag.key if survey.internal_targeting_flag else None,
                        },
                        {"key": "internal_response_sampling_flag_key", "value": None},
                    ],
                    "iteration_count": None,
                    "iteration_frequency_days": None,
                    "iteration_start_dates": [],
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                    "response_sampling_start_date": None,
                    "response_sampling_interval_type": "week",
                    "response_sampling_interval": None,
                    "response_sampling_limit": None,
                    "response_sampling_daily_limits": None,
                }
            ],
        }

    def test_updating_survey_name_validates(self):
        survey_with_targeting = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with targeting",
                "type": "popover",
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        ).json()

        self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey without targeting",
                "type": "popover",
            },
            format="json",
        ).json()

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "name": "survey without targeting",
            },
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            updated_survey_deletes_targeting_flag.json()["detail"] == "There is already another survey with this name."
        )

    @freeze_time("2023-05-01 12:00:00")
    def test_update_survey_targeting_flag_filters_records_activity(self):
        linked_flag = FeatureFlag.objects.create(team=self.team, key="linked-flag", created_by=self.user)
        targeting_flag = FeatureFlag.objects.create(team=self.team, key="targeting-flag", created_by=self.user)
        internal_targeting_flag = FeatureFlag.objects.create(
            team=self.team, key="custom-targeting-flag", created_by=self.user
        )

        survey_with_flags = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 2",
            type="popover",
            linked_flag=linked_flag,
            targeting_flag=targeting_flag,
            internal_targeting_flag=internal_targeting_flag,
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
        )

        new_filters: dict[str, Any] = {
            "targeting_flag_filters": {
                "groups": [
                    {"variant": None, "properties": [], "rollout_percentage": 69},
                    {"variant": None, "properties": [], "rollout_percentage": 75},
                ],
                "payloads": {},
                "multivariate": None,
            }
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_flags.id}/",
            data={"targeting_flag_filters": new_filters},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_activity_log = [
            {
                "user": {"first_name": self.user.first_name, "email": self.user.email},
                "activity": "updated",
                "scope": "Survey",
                "item_id": str(survey_with_flags.id),
                "detail": {
                    "changes": [
                        {
                            "type": "Survey",
                            "action": "changed",
                            "field": "targeting_flag_filters",
                            "before": {},
                            "after": new_filters,
                        },
                    ],
                    "trigger": None,
                    "name": "Survey 2",
                    "short_id": None,
                    "type": None,
                },
                "created_at": "2023-05-01T12:00:00Z",
            }
        ]

        self._assert_survey_activity(expected_activity_log)

    @freeze_time("2023-05-01 12:00:00")
    def test_create_survey_records_activity(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "New Survey",
                "type": "popover",
                "questions": [{"type": "open", "question": "What's your favorite feature?"}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        survey_id = response.json()["id"]

        self._assert_survey_activity(
            [
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email},
                    "activity": "created",
                    "scope": "Survey",
                    "item_id": survey_id,
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "New Survey",
                        "short_id": None,
                        "type": None,
                    },
                    "created_at": "2023-05-01T12:00:00Z",
                }
            ],
        )

    @freeze_time("2023-05-01 12:00:00")
    def test_update_survey_records_activity(self):
        survey = Survey.objects.create(
            team=self.team,
            name="Original Survey",
            type="popover",
            questions=[{"type": "open", "question": "Initial question?"}],
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "name": "Updated Survey",
                "questions": [{"type": "open", "question": "Updated question?", "id": str(survey.questions[0]["id"])}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self._assert_survey_activity(
            [
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email},
                    "activity": "updated",
                    "scope": "Survey",
                    "item_id": str(survey.id),
                    "detail": {
                        "changes": [
                            {
                                "type": "Survey",
                                "action": "changed",
                                "field": "name",
                                "before": "Original Survey",
                                "after": "Updated Survey",
                            },
                            {
                                "type": "Survey",
                                "action": "changed",
                                "field": "questions",
                                "before": [
                                    {
                                        "id": str(survey.questions[0]["id"]),
                                        "type": "open",
                                        "question": "Initial question?",
                                    }
                                ],
                                "after": [
                                    {
                                        "id": str(survey.questions[0]["id"]),
                                        "type": "open",
                                        "question": "Updated question?",
                                    }
                                ],
                            },
                        ],
                        "trigger": None,
                        "name": "Updated Survey",
                        "short_id": None,
                        "type": None,
                    },
                    "created_at": "2023-05-01T12:00:00Z",
                }
            ],
        )

    @patch("posthog.api.survey.report_user_action")
    @freeze_time("2023-05-01 12:00:00")
    def test_update_survey_dates_calls_report_user_action(self, mock_report_user_action):
        survey = Survey.objects.create(
            team=self.team,
            name="Date Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test question?"}],
        )

        start_date = datetime(2023, 5, 2, tzinfo=UTC)
        end_date = datetime(2023, 5, 10, tzinfo=UTC)

        # set the start date / aka launch survey
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"start_date": start_date},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_properties = {
            "name": "Date Test Survey",
            "id": survey.id,
            "survey_type": "popover",
            "question_types": ["open"],
            "created_at": survey.created_at,
        }

        mock_report_user_action.assert_called_once_with(
            self.user,
            "survey launched",
            {
                **expected_properties,
                "start_date": start_date,
                "end_date": None,
            },
            self.team,
        )
        mock_report_user_action.reset_mock()

        # set the end date / aka stop survey
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"end_date": end_date},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_report_user_action.assert_called_once_with(
            self.user,
            "survey stopped",
            {
                **expected_properties,
                "start_date": start_date,
                "end_date": end_date,
            },
            self.team,
        )
        mock_report_user_action.reset_mock()

        # remove the end date / aka resume survey
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"end_date": None},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_report_user_action.assert_called_once_with(
            self.user,
            "survey resumed",
            {
                **expected_properties,
                "start_date": start_date,
                "end_date": None,
            },
            self.team,
        )

    @freeze_time("2023-05-01 12:00:00")
    def test_delete_survey_records_activity(self):
        survey = Survey.objects.create(
            team=self.team,
            name="Survey to Delete",
            type="popover",
            questions=[{"type": "open", "question": "Question?"}],
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/surveys/{survey.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self._assert_survey_activity(
            [
                {
                    "user": {"first_name": self.user.first_name, "email": self.user.email},
                    "activity": "deleted",
                    "scope": "Survey",
                    "item_id": str(survey.id),
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "name": "Survey to Delete",
                        "short_id": None,
                        "type": None,
                    },
                    "created_at": "2023-05-01T12:00:00Z",
                }
            ],
        )

    def _assert_survey_activity(self, expected):
        activity = self.client.get(f"/api/projects/{self.team.id}/surveys/activity").json()
        self.assertEqual(activity["results"], expected)

    def test_validate_schedule_on_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey with invalid schedule",
                "type": "popover",
                "schedule": "invalid_value",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Schedule must be one of: once, recurring, always"

    def test_validate_schedule_on_update(self):
        survey = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="survey to update",
            type="popover",
            questions=[{"type": "open", "question": "Why's a hedgehog?"}],
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "schedule": "invalid_value",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Schedule must be one of: once, recurring, always"

    def test_questions_get_ids_when_creating_survey(self):
        """Test that questions get IDs assigned when creating a survey through the API."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Question ID Test Survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What do you think of this feature?",
                    },
                    {
                        "type": "rating",
                        "question": "How would you rate this feature?",
                        "scale": 5,
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()

        # Check that all questions have IDs
        for question in response_data["questions"]:
            self.assertIn("id", question)
            self.assertIsNotNone(question["id"])
            self.assertTrue(len(question["id"]) > 0)

    def test_question_ids_preserved_when_updating_survey(self):
        """Test that question IDs are preserved when updating a survey through the API."""
        # First create a survey
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Question ID Update Test",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "Original question 1",
                    },
                    {
                        "type": "rating",
                        "question": "Original question 2",
                        "scale": 5,
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        survey_data = create_response.json()
        survey_id = survey_data["id"]

        # Get the assigned question IDs
        original_question_ids = [q["id"] for q in survey_data["questions"]]

        # Update the survey with modified questions, keeping the first question's ID
        # and adding a new question without an ID
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_id}/",
            data={
                "questions": [
                    {
                        "type": "open",
                        "question": "Updated question 1",
                        "id": original_question_ids[0],  # Keep the original ID
                    },
                    {
                        "type": "open",
                        "question": "New question without ID",
                        # No ID provided, should get a new one
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        updated_data = update_response.json()

        # Check that we have 2 questions
        self.assertEqual(len(updated_data["questions"]), 2)

        # First question should keep its ID
        self.assertEqual(updated_data["questions"][0]["id"], original_question_ids[0])
