from datetime import datetime, timedelta

from unittest.mock import ANY
import pytest

from rest_framework import status
from django.core.cache import cache
from django.test.client import Client
from posthog.api.survey import nh3_clean_with_allow_list

from posthog.models.feedback.survey import Survey
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    BaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries,
    snapshot_clickhouse_queries,
    _create_event,
)

from posthog.models import FeatureFlag


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
        assert response_data["questions"] == [
            {
                "type": "open",
                "question": "What do you think of the new notebooks feature?",
            }
        ]
        assert response_data["created_by"]["id"] == self.user.id

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
                "type": "open",
                "question": "What would you want to improve from notebooks?",
            }
        ]

    def test_used_in_survey_is_populated_correctly_for_feature_flag_list(self) -> None:
        self.maxDiff = None

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

        with self.assertNumQueries(12):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = response.json()

            self.assertEqual(result["count"], 2)

            self.assertEqual(
                [(res["key"], [survey["id"] for survey in res["surveys"]]) for res in result["results"]],
                [("flag_0", []), (ff_key, [created_survey1, created_survey2])],
            )

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

        updated_survey_deletes_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={"start_date": "2023-04-01T12:00:10"},
        )

        assert updated_survey_deletes_targeting_flag.status_code == status.HTTP_200_OK
        assert updated_survey_deletes_targeting_flag.json()["name"] == "survey with targeting"
        assert updated_survey_deletes_targeting_flag.json()["targeting_flag"] is not None

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
                    "questions": [
                        {
                            "type": "open",
                            "question": "What would you want to improve from notebooks?",
                        }
                    ],
                    "appearance": None,
                    "created_at": ANY,
                    "created_by": ANY,
                    "targeting_flag": None,
                    "linked_flag": None,
                    "linked_flag_id": None,
                    "conditions": None,
                    "archived": False,
                    "start_date": None,
                    "end_date": None,
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

    def test_enable_surveys_opt_in(self):
        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 1",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=datetime.now() - timedelta(days=2),
            end_date=datetime.now() - timedelta(days=1),
        )
        self.assertEqual(self.team.surveys_opt_in, None)
        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 2",
            type="popover",
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
            start_date=datetime.now() - timedelta(days=2),
        )
        assert self.team.surveys_opt_in is True

    def test_disable_surveys_opt_in(self):
        survey = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 2",
            type="popover",
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
            start_date=datetime.now() - timedelta(days=2),
        )
        assert self.team.surveys_opt_in is True
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"end_date": datetime.now() - timedelta(days=1)},
        )
        self.team.refresh_from_db()
        assert self.team.surveys_opt_in is False

    def test_surveys_opt_in_with_api_type_surveys(self):
        api_survey = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="API survey",
            type="api",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=datetime.now() - timedelta(days=2),
        )
        self.assertEqual(self.team.surveys_opt_in, None)
        popover_survey = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Popover survey",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=datetime.now() - timedelta(days=2),
        )
        self.team.refresh_from_db()
        assert self.team.surveys_opt_in is True
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{api_survey.id}/",
            data={"end_date": datetime.now() - timedelta(days=1)},
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.surveys_opt_in, True)
        self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{popover_survey.id}/",
            data={"end_date": datetime.now() - timedelta(days=1)},
        )
        self.team.refresh_from_db()
        assert self.team.surveys_opt_in is False

    def test_surveys_opt_in_post_delete(self):
        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 1",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=datetime.now() - timedelta(days=2),
            end_date=datetime.now() - timedelta(days=1),
        )
        survey_to_delete = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 2",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=datetime.now() - timedelta(days=2),
        )
        assert self.team.surveys_opt_in is True
        self.client.delete(
            f"/api/projects/{self.team.id}/surveys/{survey_to_delete.id}/",
            format="json",
        )
        self.team.refresh_from_db()
        assert self.team.surveys_opt_in is False


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
                        "link": "bazinga.com",
                        "question": "<b>What</b> do you think of the new notebooks feature?",
                    },
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
        assert response_data["description"] == "Get feedback on the new notebooks feature"
        assert response_data["type"] == "popover"
        assert response_data["questions"] == [
            {"type": "open", "question": "What up?", "description": "check?"},
            {
                "type": "link",
                "link": "bazinga.com",
                "question": "<b>What</b> do you think of the new notebooks feature?",
            },
        ]
        assert response_data["appearance"] == {
            "thankYouMessageHeader": "Thanks for your feedback!",
            "thankYouMessageDescription": "<b>We'll use it to make notebooks better.</b>",
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
                        "link": "bazinga.com",
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
            {"type": "open", "question": "What up?", "description": "check?"},
            {
                "type": "link",
                "link": "bazinga.com",
                "question": "<b>What</b> do you think of the new notebooks feature?",
            },
        ]
        assert response_data["appearance"] == {
            "thankYouMessageDescription": "<b>We'll use it to make notebooks better.</b>",
        }
        assert response_data["created_by"]["id"] == self.user.id

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

        survey_with_flags = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey 2",
            type="popover",
            linked_flag=linked_flag,
            targeting_flag=targeting_flag,
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
        )
        self.client.logout()

        with self.assertNumQueries(2):
            response = self._get_surveys()
            assert response.status_code == status.HTTP_200_OK
            assert response.get("access-control-allow-origin") == "http://127.0.0.1:8000"
            self.assertListEqual(
                response.json()["surveys"],
                [
                    {
                        "id": str(basic_survey.id),
                        "name": "Survey 1",
                        "description": "",
                        "type": "popover",
                        "questions": [{"type": "open", "question": "What's a survey?"}],
                        "conditions": None,
                        "appearance": None,
                        "start_date": None,
                        "end_date": None,
                    },
                    {
                        "id": str(survey_with_flags.id),
                        "name": "Survey 2",
                        "description": "",
                        "type": "popover",
                        "conditions": None,
                        "appearance": None,
                        "questions": [{"type": "open", "question": "What's a hedgehog?"}],
                        "linked_flag_key": "linked-flag",
                        "targeting_flag_key": "targeting-flag",
                        "start_date": None,
                        "end_date": None,
                    },
                ],
            )


class TestResponsesCount(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_responses_count(self):
        survey_counts = {
            "d63bb580-01af-4819-aae5-edcf7ef2044f": 3,
            "fe7c4b62-8fc9-401e-b483-e4ff98fd13d5": 6,
            "daed7689-d498-49fe-936f-e85554351b6c": 100,
        }

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

    def test_responses_count_zero_responses(self):
        response = self.client.get(f"/api/projects/{self.team.id}/surveys/responses_count")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data, {})


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
