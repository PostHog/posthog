import json
import re
from datetime import datetime, timedelta, UTC
from typing import Any
from unittest.mock import ANY, patch
import uuid

import pytest
from django.core.cache import cache
from django.test.client import Client
from freezegun.api import freeze_time
from nanoid import generate
from rest_framework import status

from posthog.api.survey import nh3_clean_with_allow_list
from posthog.api.test.test_personal_api_keys import PersonalAPIKeysBaseTest
from posthog.constants import AvailableFeature
from posthog.models import Action, FeatureFlag, Team, Person
from posthog.models.cohort.cohort import Cohort
from posthog.models.surveys.survey import Survey, MAX_ITERATION_COUNT
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries,
)


class TestSurvey(APIBaseTest):
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
                        "creation_context": "surveys",
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

        # Second question should have a new ID
        self.assertIn("id", updated_data["questions"][1])
        self.assertIsNotNone(updated_data["questions"][1]["id"])
        self.assertNotIn(updated_data["questions"][1]["id"], original_question_ids)

    def test_custom_question_ids_accepted_when_creating_survey(self):
        """Test that custom question IDs are accepted when creating a survey."""
        custom_id_1 = "custom-id-1"
        custom_id_2 = "custom-id-2"

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Custom Question ID Test",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "Question with custom ID 1",
                        "id": custom_id_1,
                    },
                    {
                        "type": "open",
                        "question": "Question with custom ID 2",
                        "id": custom_id_2,
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()

        # Check that the custom IDs were preserved
        self.assertEqual(response_data["questions"][0]["id"], custom_id_1)
        self.assertEqual(response_data["questions"][1]["id"], custom_id_2)

    def test_search_survey_by_name(self):
        self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "NPS Survey 2024",
                "description": "Annual NPS survey",
                "type": "popover",
                "questions": [{"type": "open", "question": "What do you think?"}],
            },
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/?search=NPS")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "NPS Survey 2024")

    def test_search_survey_by_description(self):
        self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Product Feedback Survey",
                "description": "product feedback collection",
                "type": "popover",
                "questions": [{"type": "open", "question": "What do you think?"}],
            },
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/?search=product")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Product Feedback Survey")

    def test_search_survey_with_no_results(self):
        response = self.client.get(f"/api/projects/{self.team.id}/surveys/?search=nonexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 0)

    def test_search_survey_with_pagination(self):
        for i in range(15):
            self.client.post(
                f"/api/projects/{self.team.id}/surveys/",
                data={
                    "name": f"Product Survey {i}",
                    "description": f"Product feedback {i}",
                    "type": "popover",
                    "questions": [{"type": "open", "question": "What do you think?"}],
                    "targeting_flag_filters": None,
                },
                format="json",
            )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/?search=Product&limit=10")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 10)  # Should return only 10 results
        self.assertTrue(data["next"] is not None)  # Should have next page
        self.assertTrue(data["count"] > 10)  # Total count should be more than 10

    def test_create_survey_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            {
                "name": "Survey with custom folder",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you like to see improved?",
                    }
                ],
                "_create_in_folder": "Special Folder/Surveys",
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        survey_id = response.json()["id"]
        assert survey_id is not None

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(survey_id), type="survey").first()
        assert fs_entry is not None, "A FileSystem entry was not created for this Survey."
        assert (
            "Special Folder/Surveys" in fs_entry.path
        ), f"Expected path to include 'Special Folder/Surveys', got '{fs_entry.path}'."


class TestMultipleChoiceQuestions(APIBaseTest):
    def test_create_survey_has_open_choice(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "choices": ["Tutorials", "Customer case studies", "Product announcements", "Other"],
                        "question": "What can we do to improve our product?",
                        "buttonText": "Submit",
                        "description": "",
                        "hasOpenChoice": True,
                    }
                ],
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "<b>We'll use it to make notebooks better.<script>alert(0)</script>",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["questions"][0]["hasOpenChoice"] is True

    def test_create_survey_with_shuffle_options(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "choices": ["Tutorials", "Customer case studies", "Product announcements", "Other"],
                        "question": "What can we do to improve our product?",
                        "buttonText": "Submit",
                        "description": "",
                        "hasOpenChoice": True,
                        "shuffleOptions": True,
                    }
                ],
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "<b>We'll use it to make notebooks better.<script>alert(0)</script>",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["questions"][0]["hasOpenChoice"] is True
        assert response_data["questions"][0]["shuffleOptions"] is True


class TestSurveyQuestionValidation(APIBaseTest):
    def test_create_basic_survey_question_validation(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What up?",
                        "description": "<script>alert(0)</script>check?",
                    },
                    {
                        "type": "link",
                        "link": "https://bazinga.com",
                        "question": "<b>What</b> do you think of the new notebooks feature?",
                    },
                ],
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "<b>We'll use it to make notebooks better.<script>alert(0)</script>",
                    "shuffleQuestions": True,
                    "surveyPopupDelaySeconds": 60,
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["description"] == "Get feedback on the new notebooks feature"
        assert response_data["type"] == "popover"
        assert response_data["questions"] == [
            {
                "id": str(response_data["questions"][0]["id"]),
                "type": "open",
                "question": "What up?",
                "description": "check?",
            },
            {
                "id": str(response_data["questions"][1]["id"]),
                "type": "link",
                "link": "https://bazinga.com",
                "question": "<b>What</b> do you think of the new notebooks feature?",
            },
        ]
        assert response_data["appearance"] == {
            "thankYouMessageHeader": "Thanks for your feedback!",
            "thankYouMessageDescription": "<b>We'll use it to make notebooks better.</b>",
            "shuffleQuestions": True,
            "surveyPopupDelaySeconds": 60,
        }
        assert response_data["created_by"]["id"] == self.user.id

    def test_update_basic_survey_question_validation(self):
        basic_survey = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey without targeting",
                "type": "popover",
            },
            format="json",
        ).json()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{basic_survey['id']}/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What up?",
                        "description": "<script>alert(0)</script>check?",
                    },
                    {
                        "type": "link",
                        "link": "https://bazinga.com",
                        "question": "<b>What</b> do you think of the new notebooks feature?",
                    },
                ],
                "appearance": {
                    "thankYouMessageDescription": "<b>We'll use it to make notebooks better.<script>alert(0)</script>",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["description"] == "Get feedback on the new notebooks feature"
        assert response_data["type"] == "popover"
        assert response_data["questions"] == [
            {
                "id": str(response_data["questions"][0]["id"]),
                "type": "open",
                "question": "What up?",
                "description": "check?",
            },
            {
                "id": str(response_data["questions"][1]["id"]),
                "type": "link",
                "link": "https://bazinga.com",
                "question": "<b>What</b> do you think of the new notebooks feature?",
            },
        ]
        assert response_data["appearance"] == {
            "thankYouMessageDescription": "<b>We'll use it to make notebooks better.</b>",
        }
        assert response_data["created_by"]["id"] == self.user.id

    def test_create_validate_link_url_scheme(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey without targeting",
                "type": "popover",
                "questions": [
                    {
                        "type": "link",
                        "link": "javascript:alert(1)",
                        "question": "<b>What</b> do you think of the new notebooks feature?",
                    },
                ],
            },
            format="json",
        )

        invalid_url = "Link must be a URL with one of these schemes: [https, mailto]"

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == invalid_url

    def test_create_validate_link_mailto(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey without targeting",
                "type": "popover",
                "questions": [
                    {
                        "type": "link",
                        "link": "mailto:#@%^%#$@#$@#.com",
                        "question": "<b>What</b> do you think of the new notebooks feature?",
                    },
                ],
            },
            format="json",
        )

        invalid_url = "Invalid mailto link. Please enter a valid mailto link (e.g., mailto:example@domain.com)."

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == invalid_url

    def test_update_validate_link_https_url(self):
        basic_survey = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "survey without targeting",
                "type": "popover",
            },
            format="json",
        ).json()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{basic_survey['id']}/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "link",
                        "link": "https://#.com",
                        "question": "<b>What</b> do you think of the new notebooks feature?",
                    },
                ],
            },
            format="json",
        )
        invalid_url = "Invalid HTTPS URL. Please enter a valid HTTPS link."

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == invalid_url

    def test_cleaning_empty_questions(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [],
                "appearance": {
                    "thankYouMessageHeader": " ",
                    "thankYouMessageDescription": "",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Notebooks beta release survey"
        assert response_data["questions"] == []
        assert response_data["appearance"] == {
            "thankYouMessageHeader": " ",
            "thankYouMessageDescription": "",
        }

    def test_validate_thank_you_with_invalid_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "appearance": "invalid",
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Appearance must be an object"

    def test_validate_question_with_missing_text(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [{"type": "open"}],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Question text is required"

    def test_validate_malformed_questions(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": "",
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Questions must be a list of objects"

    def test_validate_malformed_questions_as_string(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": "this is my question",
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Questions must be a list of objects"

    def test_validate_malformed_questions_as_array_of_strings(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": ["this is my question"],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Questions must be a list of objects"

    def test_validate_malformed_question_choices_as_string(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "question": "this is my question",
                        "type": "multiple_choice",
                        "choices": "these are my question choices",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Question choices must be a list of strings"

    def test_validate_malformed_question_choices_as_array_of_empty_strings(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "question": "this is my question",
                        "type": "multiple_choice",
                        "choices": ["", ""],
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Question choices cannot be empty"


class TestSurveyQuestionValidationWithEnterpriseFeatures(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization = self.create_organization_with_features([AvailableFeature.SURVEYS_TEXT_HTML])
        self.team = self.create_team_with_organization(self.organization)
        self.user = self.create_user_with_organization(self.organization)
        self.client.force_login(self.user)

    def test_create_survey_with_valid_question_description_content_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "This is a description",
                        "descriptionContentType": "text",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["questions"][0]["descriptionContentType"] == "text"

    def test_validate_question_description_content_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "This is a description",
                        "descriptionContentType": "text/html",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Question descriptionContentType must be one of ['text', 'html']"

    def test_create_survey_with_valid_thank_you_description_content_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "This is a thank you message",
                    "thankYouMessageDescriptionContentType": "text",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["appearance"]["thankYouMessageDescriptionContentType"] == "text"

    def test_validate_thank_you_description_content_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "This is a thank you message",
                    "thankYouMessageDescriptionContentType": "text/html",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "thankYouMessageDescriptionContentType must be one of ['text', 'html']"

    def test_create_survey_with_survey_popup_delay(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "type": "popover",
                "appearance": {
                    "surveyPopupDelaySeconds": 6000,
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["appearance"]["surveyPopupDelaySeconds"] == 6000

    def test_validate_survey_popup_delay(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "type": "popover",
                "appearance": {
                    "surveyPopupDelaySeconds": -100,
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "Survey popup delay seconds must be a positive integer"

    def test_create_survey_with_valid_question_description_content_type_html(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "<b>This is a description</b>",
                        "descriptionContentType": "html",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["questions"][0]["descriptionContentType"] == "html"
        assert response_data["questions"][0]["description"] == "<b>This is a description</b>"

    def test_create_survey_with_html_without_feature_flag(self):
        # Remove the SURVEYS_TEXT_HTML feature
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "<b>This is a description</b>",
                        "descriptionContentType": "html",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert response_data["detail"] == "You need to upgrade to PostHog Enterprise to use HTML in survey questions"

    def test_create_survey_with_valid_thank_you_description_content_type_html(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "<b>This is a thank you message</b>",
                    "thankYouMessageDescriptionContentType": "html",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert Survey.objects.filter(id=response_data["id"]).exists()
        assert response_data["appearance"]["thankYouMessageDescriptionContentType"] == "html"
        assert response_data["appearance"]["thankYouMessageDescription"] == "<b>This is a thank you message</b>"

    def test_create_survey_with_html_thank_you_without_feature_flag(self):
        # Remove the SURVEYS_TEXT_HTML feature
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "<b>This is a thank you message</b>",
                    "thankYouMessageDescriptionContentType": "html",
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert (
            response_data["detail"]
            == "You need to upgrade to PostHog Enterprise to use HTML in survey thank you message"
        )


class TestSurveyWithActions(APIBaseTest):
    def test_cannot_use_actions_with_properties(self):
        action = Action.objects.create(
            team=self.team,
            name="person subscribed",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "docs",
                    "url_matching": "contains",
                    "properties": {"type": "person", "key": "val"},
                }
            ],
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "conditions": {
                    "actions": {"values": [{"name": "person subscribed", "id": action.id}]},
                },
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "This is a description",
                        "descriptionContentType": "text",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert (
            response.json()["detail"] == "Survey cannot be activated by an Action with property filters defined on it."
        )

    def test_can_set_associated_actions(self):
        user_subscribed_action = Action.objects.create(
            team=self.team,
            name="user subscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        user_unsubscribed_action = Action.objects.create(
            team=self.team,
            name="user unsubscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "conditions": {
                    "actions": {
                        "values": [
                            {"name": "user subscribed", "id": user_subscribed_action.id},
                            {"name": "user unsubscribed", "id": user_unsubscribed_action.id},
                        ]
                    },
                },
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "This is a description",
                        "descriptionContentType": "text",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        survey = Survey.objects.get(id=response_data["id"])
        assert survey is not None
        assert len(survey.actions.all()) == 2
        assert survey.actions.filter(name="user subscribed").exists()
        assert survey.actions.filter(name="user unsubscribed").exists()

    def test_can_remove_associated_actions(self):
        user_subscribed_action = Action.objects.create(
            team=self.team,
            name="user subscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )
        Action.objects.create(
            team=self.team,
            name="user unsubscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        survey_with_actions = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="survey with actions",
            type="popover",
            questions=[{"type": "open", "question": "Why's a hedgehog?"}],
        )
        survey_with_actions.actions.set(Action.objects.filter(name__in=["user subscribed", "user unsubscribed"]))
        survey_with_actions.save()
        assert survey_with_actions.actions.filter(name="user unsubscribed").exists()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_actions.id}/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "conditions": {
                    "actions": {"values": [{"name": "user subscribed", "id": user_subscribed_action.id}]},
                },
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "This is a description",
                        "descriptionContentType": "text",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK, response_data
        survey = Survey.objects.get(id=response_data["id"])
        assert survey is not None
        assert len(survey.actions.all()) == 1
        assert survey.actions.filter(name="user subscribed").exists()
        assert not survey.actions.filter(name="user unsubscribed").exists()

    def test_can_clear_associated_actions(self):
        Action.objects.create(
            team=self.team,
            name="user subscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )
        Action.objects.create(
            team=self.team,
            name="user unsubscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        survey_with_actions = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="survey with actions",
            type="popover",
            questions=[{"type": "open", "question": "Why's a hedgehog?"}],
        )
        survey_with_actions.actions.set(Action.objects.filter(name__in=["user subscribed", "user unsubscribed"]))
        survey_with_actions.save()
        assert survey_with_actions.actions.filter(name="user subscribed").exists()
        assert survey_with_actions.actions.filter(name="user unsubscribed").exists()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_actions.id}/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "conditions": {
                    "actions": {"values": []},
                },
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                        "description": "This is a description",
                        "descriptionContentType": "text",
                    }
                ],
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK, response_data
        survey = Survey.objects.get(id=response_data["id"])
        assert survey is not None
        assert len(survey.actions.all()) == 0


@freeze_time("2024-12-12 00:00:00")
class TestSurveyResponseSampling(APIBaseTest):
    def _create_survey_with_sampling_limits(
        self,
        response_sampling_interval_type,
        response_sampling_interval,
        response_sampling_limit,
        response_sampling_start_date,
    ) -> Survey:
        random_id = generate("1234567890abcdef", 10)
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": f"Survey with adaptive response collection {random_id}",
                "description": "Collect survey responses over a period of time",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                    }
                ],
                "response_sampling_interval_type": response_sampling_interval_type,
                "response_sampling_interval": response_sampling_interval,
                "response_sampling_limit": response_sampling_limit,
                "response_sampling_start_date": response_sampling_start_date,
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        survey = Survey.objects.get(id=response_data["id"])
        return survey

    def test_can_create_survey_with_adaptive_responses(self):
        survey = self._create_survey_with_sampling_limits("day", 10, 500, datetime(2024, 12, 12))
        assert survey.response_sampling_daily_limits is not None
        schedule = json.loads(survey.response_sampling_daily_limits)
        self.assertEqual(len(schedule), 10)
        for day, entry in enumerate(schedule):
            self.assertEqual(entry["daily_response_limit"], 50 * (day + 1))
            self.assertEqual(entry["rollout_percentage"], 10 * (day + 1))

    def test_can_remove_adaptive_response_sampling(self):
        survey = self._create_survey_with_sampling_limits("day", 10, 500, datetime(2024, 12, 12))
        assert survey.response_sampling_daily_limits is not None
        schedule = json.loads(survey.response_sampling_daily_limits)
        self.assertEqual(len(schedule), 10)
        for day, entry in enumerate(schedule):
            self.assertEqual(entry["daily_response_limit"], 50 * (day + 1))
            self.assertEqual(entry["rollout_percentage"], 10 * (day + 1))

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "response_sampling_interval_type": None,
                "response_sampling_interval": None,
                "response_sampling_limit": None,
                "response_sampling_start_date": None,
            },
        )
        response_data = response.json()
        survey = Survey.objects.get(id=response_data["id"])
        assert survey.response_sampling_daily_limits is None

    def test_can_create_targeting_flag_if_does_not_exist(self):
        survey = self._create_survey_with_sampling_limits("day", 10, 500, datetime(2024, 12, 12))
        assert survey.response_sampling_daily_limits is not None
        assert survey.internal_response_sampling_flag is not None
        assert survey.internal_response_sampling_flag.filters == {
            "groups": [{"properties": [], "rollout_percentage": 100, "variant": ""}]
        }


class TestSurveysRecurringIterations(APIBaseTest):
    def _create_recurring_survey(self) -> Survey:
        random_id = generate("1234567890abcdef", 10)
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": f"Recurring NPS Survey {random_id}",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                    }
                ],
                "iteration_count": 2,
                "iteration_frequency_days": 30,
            },
        )

        response_data = response.json()
        assert response_data["iteration_start_dates"] is None
        assert response_data["current_iteration"] is None
        survey = Survey.objects.get(id=response_data["id"])
        return survey

    def _create_non_recurring_survey(self) -> Survey:
        random_id = generate("1234567890abcdef", 10)
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": f"Recurring NPS Survey {random_id}",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What's a survey?",
                    }
                ],
            },
        )

        response_data = response.json()
        survey = Survey.objects.get(id=response_data["id"])
        return survey

    def test_can_create_recurring_survey(self):
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 2,
                "iteration_frequency_days": 30,
            },
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1

    def test_can_create_and_launch_recurring_survey(self):
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
            },
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1

    def test_can_set_internal_targeting_flag(self):
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 2,
                "iteration_frequency_days": 30,
            },
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1
        survey.refresh_from_db()
        assert survey.internal_targeting_flag
        survey_id = response_data["id"]
        user_submitted_dismissed_filter = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$survey_dismissed/{survey_id}/1",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                        {
                            "key": f"$survey_responded/{survey_id}/1",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                }
            ]
        }

        assert survey.internal_targeting_flag.filters == user_submitted_dismissed_filter

    @freeze_time("2024-05-22 14:40:09")
    def test_iterations_always_start_from_start_date(self):
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"start_date": datetime.now(), "iteration_count": 2, "iteration_frequency_days": 30},
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1
        assert response_data["iteration_start_dates"] == ["2024-05-22T14:40:09Z", "2024-06-21T14:40:09Z"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"iteration_count": 4, "iteration_frequency_days": 30},
        )
        response_data = response.json()
        assert len(response_data["iteration_start_dates"]) == 4
        assert response_data["iteration_start_dates"] == [
            "2024-05-22T14:40:09Z",
            "2024-06-21T14:40:09Z",
            "2024-07-21T14:40:09Z",
            "2024-08-20T14:40:09Z",
        ]

    def test_cannot_reduce_iterations_lt_current_iteration(self):
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 2,
                "iteration_frequency_days": 30,
            },
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1

        survey.refresh_from_db()
        survey.current_iteration = 2
        survey.save()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 1,
                "iteration_frequency_days": 30,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Cannot change survey recurrence to 1, should be at least 2"

    def test_can_handle_non_nil_current_iteration(self):
        survey = self._create_non_recurring_survey()
        survey.current_iteration = 2
        survey.save()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
            },
        )
        assert response.status_code == status.HTTP_200_OK

    def test_guards_for_nil_iteration_count(self):
        survey = self._create_recurring_survey()
        survey.current_iteration = 2
        survey.save()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
            },
        )
        assert response.status_code == status.HTTP_200_OK
        survey.refresh_from_db()
        self.assertIsNotNone(survey.current_iteration)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 3,
                "iteration_frequency_days": 30,
            },
        )
        assert response.status_code == status.HTTP_200_OK

    def test_can_turn_off_recurring_schedule(self):
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 0,
            },
        )
        response_data = response.json()
        assert len(response_data["iteration_start_dates"]) == 0
        assert response_data["current_iteration"] is None

    def test_can_stop_and_resume_survey(self):
        # start the survey with a recurring schedule
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "iteration_count": 2,
                "iteration_frequency_days": 30,
            },
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1

        survey.refresh_from_db()

        # now stop  the survey with a recurring schedule
        survey = self._create_recurring_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={
                "start_date": datetime.now() - timedelta(days=1),
                "end_date": datetime.now() + timedelta(days=2),
                "iteration_count": 2,
                "iteration_frequency_days": 30,
            },
        )
        response_data = response.json()
        assert response_data["iteration_start_dates"] is not None
        assert len(response_data["iteration_start_dates"]) == 2
        assert response_data["current_iteration"] == 1


class TestSurveysAPIList(BaseTest, QueryMatchingTest):
    def setUp(self):
        cache.clear()
        super().setUp()
        # it is really important to know that this is CSRF exempt
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _get_surveys(
        self,
        token=None,
        origin="http://127.0.0.1:8000",
        ip="127.0.0.1",
    ):
        return self.client.get(
            "/api/surveys/",
            data={"token": token or self.team.api_token},
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    def test_can_get_survey_config(self):
        survey_appearance = {
            "thankYouMessageHeader": "Thanks for your feedback!",
            "thankYouMessageDescription": "We'll use it to make notebooks better",
        }
        self.team.survey_config = {"appearance": survey_appearance}

        self.team.save()

        self.team = Team.objects.get(id=self.team.id)

        self.client.logout()
        response = self._get_surveys()
        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK, response_data
        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["survey_config"] is not None
        assert response_data["survey_config"]["appearance"] == survey_appearance

    def test_list_surveys_with_actions(self):
        action = Action.objects.create(
            team=self.team,
            name="user subscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        survey_with_actions = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="survey with actions",
            type="popover",
            questions=[{"type": "open", "question": "Why's a hedgehog?"}],
        )
        survey_with_actions.actions.set(Action.objects.filter(name="user subscribed"))
        survey_with_actions.save()
        self.client.logout()

        with self.assertNumQueries(3):
            response = self._get_surveys()
            assert response.status_code == status.HTTP_200_OK
            assert response.get("access-control-allow-origin") == "http://127.0.0.1:8000"
            self.assertListEqual(
                response.json()["surveys"],
                [
                    {
                        "id": str(survey_with_actions.id),
                        "name": "survey with actions",
                        "type": "popover",
                        "questions": [
                            {
                                "id": str(survey_with_actions.questions[0]["id"]),
                                "type": "open",
                                "question": "Why's a hedgehog?",
                            }
                        ],
                        "conditions": {
                            "actions": {
                                "values": [
                                    {
                                        "id": action.id,
                                        "name": "user subscribed",
                                        "steps": [
                                            {
                                                "event": "$pageview",
                                                "properties": None,
                                                "selector": None,
                                                "tag_name": None,
                                                "text": None,
                                                "text_matching": None,
                                                "href": None,
                                                "href_matching": None,
                                                "url": "docs",
                                                "url_matching": "contains",
                                            }
                                        ],
                                    }
                                ]
                            }
                        },
                        "appearance": None,
                        "start_date": None,
                        "end_date": None,
                        "current_iteration": None,
                        "current_iteration_start_date": None,
                        "schedule": "once",
                        "enable_partial_responses": False,
                    }
                ],
            )

    @snapshot_postgres_queries
    def test_list_surveys(self):
        basic_survey = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 1",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
        )
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

        self.client.logout()

        with self.assertNumQueries(3):
            response = self._get_surveys()
            assert response.status_code == status.HTTP_200_OK
            assert response.get("access-control-allow-origin") == "http://127.0.0.1:8000"
            surveys = response.json()["surveys"]
            self.assertIn(
                {
                    "id": str(survey_with_flags.id),
                    "name": "Survey 2",
                    "type": "popover",
                    "conditions": None,
                    "appearance": None,
                    "questions": [
                        {
                            "id": str(survey_with_flags.questions[0]["id"]),
                            "type": "open",
                            "question": "What's a hedgehog?",
                        }
                    ],
                    "linked_flag_key": "linked-flag",
                    "targeting_flag_key": "targeting-flag",
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                    "internal_targeting_flag_key": "custom-targeting-flag",
                    "start_date": None,
                    "end_date": None,
                    "schedule": "once",
                    "enable_partial_responses": False,
                },
                surveys,
            )
            self.assertIn(
                {
                    "id": str(basic_survey.id),
                    "name": "Survey 1",
                    "type": "popover",
                    "questions": [
                        {"id": str(basic_survey.questions[0]["id"]), "type": "open", "question": "What's a survey?"}
                    ],
                    "conditions": None,
                    "appearance": None,
                    "start_date": None,
                    "end_date": None,
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                    "schedule": "once",
                    "enable_partial_responses": False,
                },
                surveys,
            )

    def test_list_surveys_excludes_description(self):
        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 1",
            description="This description should not be returned",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
        )
        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 2",
            description="Another description that should be excluded",
            type="popover",
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
        )
        self.client.logout()

        with self.assertNumQueries(3):
            response = self._get_surveys()
            assert response.status_code == status.HTTP_200_OK
            assert response.get("access-control-allow-origin") == "http://127.0.0.1:8000"

            surveys = response.json()["surveys"]
            assert len(surveys) == 2

            for survey in surveys:
                assert "description" not in survey, f"Description field should not be present in survey: {survey}"

            assert len(surveys) == 2


class TestSurveyAPITokens(PersonalAPIKeysBaseTest, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.key.scopes = ["survey:read"]
        self.key.save()

    @freeze_time("2024-05-01 14:40:09")
    def test_responses_count_works_with_survey_read(self):
        survey_counts = {
            "d63bb580-01af-4819-aae5-edcf7ef2044f": 3,
            "fe7c4b62-8fc9-401e-b483-e4ff98fd13d5": 6,
            "daed7689-d498-49fe-936f-e85554351b6c": 100,
        }

        earliest_survey = Survey.objects.create(team_id=self.team.id)
        earliest_survey.start_date = datetime.now() - timedelta(days=101)
        earliest_survey.save()

        for survey_id, count in survey_counts.items():
            for _ in range(count):
                _create_event(
                    event="survey sent",
                    team=self.team,
                    distinct_id=self.user.id,
                    properties={"$survey_id": survey_id},
                    timestamp=datetime.now() - timedelta(days=count),
                )

        response = self._do_request(f"/api/projects/{self.team.id}/surveys/responses_count")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data, survey_counts)


class TestResponsesCount(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    @freeze_time("2024-05-01 14:40:09")
    def test_responses_count(self):
        survey_counts = {
            "d63bb580-01af-4819-aae5-edcf7ef2044f": 3,
            "fe7c4b62-8fc9-401e-b483-e4ff98fd13d5": 6,
            "daed7689-d498-49fe-936f-e85554351b6c": 100,
        }

        earliest_survey = Survey.objects.create(team_id=self.team.id)
        earliest_survey.start_date = datetime.now() - timedelta(days=101)
        earliest_survey.save()

        for survey_id, count in survey_counts.items():
            for _ in range(count):
                _create_event(
                    event="survey sent",
                    team=self.team,
                    distinct_id=self.user.id,
                    properties={"$survey_id": survey_id},
                    timestamp=datetime.now() - timedelta(days=count),
                )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/responses_count")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data, survey_counts)

    @snapshot_clickhouse_queries
    @freeze_time("2024-05-01 14:40:09")
    def test_responses_count_only_after_first_survey_started(self):
        survey_counts = {
            "d63bb580-01af-4819-aae5-edcf7ef2044f": 3,
            "fe7c4b62-8fc9-401e-b483-e4ff98fd13d5": 6,
            "daed7689-d498-49fe-936f-e85554351b6c": 100,
        }

        expected_survey_counts = {
            "d63bb580-01af-4819-aae5-edcf7ef2044f": 3,
            "fe7c4b62-8fc9-401e-b483-e4ff98fd13d5": 6,
        }

        earliest_survey = Survey.objects.create(team_id=self.team.id)
        earliest_survey.start_date = datetime.now() - timedelta(days=6)
        earliest_survey.save()

        for survey_id, count in survey_counts.items():
            for _ in range(count):
                _create_event(
                    event="survey sent",
                    team=self.team,
                    distinct_id=self.user.id,
                    properties={"$survey_id": survey_id},
                    timestamp=datetime.now() - timedelta(days=count),
                )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/responses_count")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data, expected_survey_counts)

    def test_responses_count_zero_responses(self):
        response = self.client.get(f"/api/projects/{self.team.id}/surveys/responses_count")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data, {})

    @snapshot_clickhouse_queries
    @freeze_time("2024-06-11 11:00:00")
    def test_responses_count_with_partial_responses(self):
        survey1_id = str(uuid.uuid4())
        survey2_id = str(uuid.uuid4())

        sub_id_1 = str(uuid.uuid4())  # Submission ID for survey 1, user 1
        sub_id_2 = str(uuid.uuid4())  # Submission ID for survey 1, user 2
        sub_id_3 = str(uuid.uuid4())  # Submission ID for survey 2, user 1

        user_1_did = str(uuid.uuid4())
        user_2_did = str(uuid.uuid4())

        # Need at least one survey with a start date for the query to work
        Survey.objects.create(team_id=self.team.id, id=survey1_id, start_date=datetime.now() - timedelta(days=1))

        events_data = [
            # Survey 1, User 1: Legacy + 2 partials (latest should count)
            {
                "event": "survey sent",
                "distinct_id": user_1_did,
                "timestamp": "2024-06-11 10:00:00",
                "properties": {"$survey_id": survey1_id, "$response": "legacy"},
            },
            {
                "event": "survey sent",
                "distinct_id": user_1_did,
                "timestamp": "2024-06-11 10:05:00",
                "properties": {"$survey_id": survey1_id, "$survey_submission_id": sub_id_1, "$response": "partial1"},
            },
            {
                "event": "survey sent",
                "distinct_id": user_1_did,
                "timestamp": "2024-06-11 10:06:00",  # Latest for sub_id_1
                "properties": {"$survey_id": survey1_id, "$survey_submission_id": sub_id_1, "$response": "partial2"},
            },
            # Survey 1, User 2: One partial submission
            {
                "event": "survey sent",
                "distinct_id": user_2_did,
                "timestamp": "2024-06-11 10:10:00",
                "properties": {
                    "$survey_id": survey1_id,
                    "$survey_submission_id": sub_id_2,
                    "$response": "user2_partial",
                },
            },
            # Survey 2, User 1: One partial submission
            {
                "event": "survey sent",
                "distinct_id": user_1_did,
                "timestamp": "2024-06-11 10:15:00",
                "properties": {
                    "$survey_id": survey2_id,
                    "$survey_submission_id": sub_id_3,
                    "$response": "survey2_partial",
                },
            },
            # Survey 2, User 2: Legacy
            {
                "event": "survey sent",
                "distinct_id": user_2_did,
                "timestamp": "2024-06-11 10:20:00",
                "properties": {"$survey_id": survey2_id, "$response": "survey2_legacy"},
            },
            # An old event outside the implicit time range (based on survey start date)
            {
                "event": "survey sent",
                "distinct_id": user_1_did,
                "timestamp": "2024-06-09 10:00:00",
                "properties": {"$survey_id": survey1_id, "$response": "too_old"},
            },
        ]

        for event_data in events_data:
            _create_event(
                team=self.team,
                event=event_data["event"],
                distinct_id=event_data["distinct_id"],
                timestamp=event_data["timestamp"],
                properties=event_data["properties"],
            )

        with patch("posthog.api.survey.SurveyViewSet.is_partial_responses_enabled", return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/surveys/responses_count")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        # Expected counts:
        # Survey 1: 1 (legacy) + 1 (latest for sub_id_1) + 1 (sub_id_2) = 3
        # Survey 2: 1 (sub_id_3) + 1 (legacy) = 2
        expected_counts = {
            survey1_id: 3,
            survey2_id: 2,
        }

        self.assertEqual(data, expected_counts)


class TestSurveyStats(ClickhouseTestMixin, APIBaseTest):
    def test_survey_stats_nonexistent_survey(self):
        response = self.client.get(f"/api/projects/{self.team.id}/surveys/12345/stats/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_survey_stats_zero_responses(self):
        survey = Survey.objects.create(
            team=self.team,
            name="My Survey",
            type="popover",
            questions=[{"type": "open", "question": "What's your favorite color?"}],
        )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/{survey.id}/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        stats = data["stats"]
        for event_type in ["survey shown", "survey dismissed", "survey sent"]:
            self.assertEqual(stats[event_type]["total_count"], 0)
            self.assertEqual(stats[event_type]["unique_persons"], 0)
            self.assertEqual(stats[event_type]["first_seen"], None)
            self.assertEqual(stats[event_type]["last_seen"], None)

        rates = data["rates"]
        self.assertEqual(rates["response_rate"], 0.0)
        self.assertEqual(rates["dismissal_rate"], 0.0)

    def test_global_stats_no_surveys(self):
        response = self.client.get(f"/api/projects/{self.team.id}/surveys/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        stats = data["stats"]
        self.assertEqual(stats, {})
        rates = data["rates"]
        self.assertEqual(rates["response_rate"], 0.0)
        self.assertEqual(rates["dismissal_rate"], 0.0)

    def test_global_stats_archived_surveys(self):
        # Create one active and one archived survey
        active_survey = Survey.objects.create(
            team=self.team,
            name="Active Survey",
            type="popover",
            questions=[{"type": "open", "question": "Question?"}],
        )
        archived_survey = Survey.objects.create(
            team=self.team,
            name="Archived Survey",
            type="popover",
            questions=[{"type": "open", "question": "Question?"}],
            archived=True,
        )

        user_1 = Person.objects.create(team=self.team, distinct_ids=[str(uuid.uuid4())])
        user_2 = Person.objects.create(team=self.team, distinct_ids=[str(uuid.uuid4())])

        # Insert events for both surveys
        events = [
            # Active survey events
            ("survey shown", "2024-05-01 12:00:00", user_1.distinct_ids[0], active_survey.id),
            ("survey sent", "2024-05-01 12:01:00", user_1.distinct_ids[0], active_survey.id),
            ("survey shown", "2024-05-01 12:00:00", user_1.distinct_ids[0], active_survey.id),
            ("survey sent", "2024-05-01 12:01:00", user_1.distinct_ids[0], active_survey.id),
            # Archived survey events
            ("survey shown", "2024-05-01 13:00:00", user_2.distinct_ids[0], archived_survey.id),
            ("survey sent", "2024-05-01 13:01:00", user_2.distinct_ids[0], archived_survey.id),
        ]

        for event, timestamp, distinct_id, survey_id in events:
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties={"$survey_id": str(survey_id)},
            )

        response = self.client.get(f"/api/projects/{self.team.id}/surveys/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        stats = data["stats"]

        # Should only include stats from active survey
        self.assertEqual(stats["survey shown"]["total_count"], 2)
        self.assertEqual(stats["survey sent"]["total_count"], 2)
        self.assertEqual(stats["survey shown"]["unique_persons"], 1)
        self.assertEqual(stats["survey sent"]["unique_persons"], 1)

        rates = data["rates"]
        self.assertEqual(rates["response_rate"], 100.0)  # 1 sent / 1 shown
        self.assertEqual(rates["dismissal_rate"], 0.0)  # 0 dismissed / 1 shown

    @freeze_time("2024-06-10 10:00:00")
    def test_survey_stats_partial_responses(self):
        survey = Survey.objects.create(
            team=self.team,
            name="Partial Response Survey",
            type="popover",
            questions=[{"type": "open", "question": "How are you?"}],
            enable_partial_responses=True,  # Enable partial responses
        )
        sub_id_1 = str(uuid.uuid4())
        sub_id_2 = str(uuid.uuid4())
        user_1 = Person.objects.create(team=self.team, distinct_ids=[str(uuid.uuid4())])
        user_2 = Person.objects.create(team=self.team, distinct_ids=[str(uuid.uuid4())])
        user_3 = Person.objects.create(team=self.team, distinct_ids=[str(uuid.uuid4())])

        # Events:
        # user_1: shown -> sent (legacy) -> sent (partial 1, ts1) -> sent (partial 1, ts2)
        # user_2: shown -> dismissed -> sent (partial 2)
        events_data = [
            {
                "event": "survey shown",
                "distinct_id": user_1.distinct_ids[0],
                "timestamp": "2024-06-10 09:00:00",
                "properties": {"$survey_id": str(survey.id)},
            },
            {
                "event": "survey shown",
                "distinct_id": user_2.distinct_ids[0],
                "timestamp": "2024-06-10 09:01:00",
                "properties": {"$survey_id": str(survey.id)},
            },
            {
                "event": "survey shown",
                "distinct_id": user_3.distinct_ids[0],
                "timestamp": "2024-06-10 09:01:00",
                "properties": {"$survey_id": str(survey.id)},
            },
            {
                "event": "survey dismissed",
                "distinct_id": user_3.distinct_ids[0],
                "timestamp": "2024-06-10 09:02:00",
                "properties": {"$survey_id": str(survey.id)},
            },
            # Legacy submission (no submission_id)
            {
                "event": "survey sent",
                "distinct_id": user_1.distinct_ids[0],
                "timestamp": "2024-06-10 09:05:00",
                "properties": {"$survey_id": str(survey.id), "$survey_response_question_id": "ok"},
            },
            # Partial submission 1, first event
            {
                "event": "survey sent",
                "distinct_id": user_1.distinct_ids[0],
                "timestamp": "2024-06-10 09:10:00",
                "properties": {
                    "$survey_id": str(survey.id),
                    "$survey_submission_id": sub_id_1,
                    "$survey_response_question_id": "good",
                },
            },
            # Partial submission 1, second (later) event - should be the one counted for sub_id_1
            {
                "event": "survey sent",
                "distinct_id": user_1.distinct_ids[0],
                "timestamp": "2024-06-10 09:11:00",
                "properties": {
                    "$survey_id": str(survey.id),
                    "$survey_submission_id": sub_id_1,
                    "$survey_response_question_id": "great",
                },
            },
            # Partial submission 2
            {
                "event": "survey sent",
                "distinct_id": user_2.distinct_ids[0],
                "timestamp": "2024-06-10 09:15:00",
                "properties": {
                    "$survey_id": str(survey.id),
                    "$survey_submission_id": sub_id_2,
                    "$survey_response_question_id": "fine",
                },
            },
        ]

        for event in events_data:
            _create_event(
                team=self.team,
                event=event["event"],
                distinct_id=event["distinct_id"],
                timestamp=event["timestamp"],
                properties=event["properties"],
            )

        flush_persons_and_events()

        with patch("posthog.api.survey.SurveyViewSet.is_partial_responses_enabled", return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/surveys/{survey.id}/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data: dict[str, Any] = response.json()
        stats: dict[str, Any] = data["stats"]  # Use Any for the inner value type

        # Check counts based on unique events/persons
        self.assertEqual(stats["survey shown"]["total_count"], 3)
        self.assertEqual(stats["survey shown"]["unique_persons"], 3)

        self.assertEqual(stats["survey dismissed"]["total_count"], 1)
        self.assertEqual(stats["survey dismissed"]["unique_persons"], 1)

        # Check 'survey sent' stats - should count unique submissions
        # 1 legacy + 1 for sub_id_1 (latest) + 1 for sub_id_2 = 3 unique submissions
        self.assertEqual(stats["survey sent"]["total_count"], 3)
        # user_1 submitted legacy and sub_id_1, user_2 submitted sub_id_2
        self.assertEqual(stats["survey sent"]["unique_persons"], 2)

        # Check rates (based on unique persons)
        # Re-assign rates here, as the previous assignment might have type issues
        rates_reassigned: dict[str, float] = data["rates"]
        # (Unique persons sent / Unique persons shown) * 100 = (2 / 2) * 100 = 100.0
        self.assertEqual(rates_reassigned["response_rate"], 100.0)
        # (Unique persons dismissed / Unique persons shown) * 100 = (1 / 3) * 100 = 33.33
        self.assertEqual(rates_reassigned["dismissal_rate"], 33.33)


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (
            """
        <div style="display: flex; justify-content: center;">
                <div style="flex: 1;">
                    <img src="https://www.gardenhealth.com/wp-content/uploads/2019/09/hedgehog_octobergardeningjobs-768x768.webp" alt="Your Image" style="max-width: 100%; height: auto;   opacity: 1;">
                </div>
                <div style="flex: 3; padding:10px;">
                    <p>Help us stay sharp.</p>
        </div>
      """,
            """
        <div style="display: flex; justify-content: center;">
                <div style="flex: 1;">
                    <img src="https://www.gardenhealth.com/wp-content/uploads/2019/09/hedgehog_octobergardeningjobs-768x768.webp" alt="Your Image" style="max-width: 100%; height: auto;   opacity: 1;">
                </div>
                <div style="flex: 3; padding:10px;">
                    <p>Help us stay sharp.</p>
                </div>
        </div>""",
        ),
        (""" """, """ """),
    ],
)
def test_nh3_clean_configuration(test_input, expected):
    assert nh3_clean_with_allow_list(test_input).replace(" ", "") == expected.replace(" ", "")
