from unittest.mock import ANY

from rest_framework import status
from django.core.cache import cache
from django.test.client import Client

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feedback.survey import Survey

from posthog.test.base import APIBaseTest, BaseTest, QueryMatchingTest, snapshot_postgres_queries


class TestSurvey(APIBaseTest):
    def test_can_create_basic_survey(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks beta release survey",
                "description": "Get feedback on the new notebooks feature",
                "type": "popover",
                "questions": [{"type": "open", "question": "What do you think of the new notebooks feature?"}],
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
            {"type": "open", "question": "What do you think of the new notebooks feature?"}
        ]
        assert response_data["created_by"]["id"] == self.user.id

    def test_can_create_survey_with_linked_flag_and_targeting(self):
        notebooks_flag = FeatureFlag.objects.create(team=self.team, key="notebooks", created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [{"type": "open", "question": "What would you want to improve from notebooks?"}],
                "linked_flag_id": notebooks_flag.id,
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {"key": "billing_plan", "value": ["cloud"], "operator": "exact", "type": "person"}
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
                    "properties": [{"key": "billing_plan", "value": ["cloud"], "operator": "exact", "type": "person"}],
                    "rollout_percentage": None,
                }
            ]
        }
        assert response_data["conditions"] == {"url": "https://app.posthog.com/notebooks"}
        assert response_data["questions"] == [
            {"type": "open", "question": "What would you want to improve from notebooks?"}
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
                "questions": [{"type": "open", "question": "What would you want to improve from notebooks?"}],
                "linked_flag_id": notebooks_flag.id,
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {"key": "billing_plan", "value": ["cloud"], "operator": "exact", "type": "person"}
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
                "questions": [{"type": "open", "question": "What would you want to improve from notebooks?"}],
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
            data={"name": f"flag", "key": f"flag_0", "filters": {"groups": [{"rollout_percentage": 5}]}},
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
                                {"key": "billing_plan", "value": ["cloud"], "operator": "exact", "type": "person"}
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
                                {"key": "email", "value": ["max@posthog.com"], "operator": "exact", "type": "person"}
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
                    "properties": [{"key": "billing_plan", "value": ["cloud"], "operator": "exact", "type": "person"}],
                    "rollout_percentage": None,
                }
            ]
        }
        updated_survey_updates_targeting_flag = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey_with_targeting['id']}/",
            data={
                "targeting_flag_filters": {"groups": [{"variant": None, "rollout_percentage": None, "properties": []}]},
            },
        )
        assert updated_survey_updates_targeting_flag.status_code == status.HTTP_200_OK
        assert FeatureFlag.objects.filter(id=survey_with_targeting["targeting_flag"]["id"]).get().filters == {
            "groups": [{"variant": None, "properties": [], "rollout_percentage": None}]
        }

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
                                {"key": "billing_plan", "value": ["cloud"], "operator": "exact", "type": "person"}
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

    def test_can_list_surveys(self):
        self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "description": "Make notebooks better",
                "questions": [{"type": "open", "question": "What would you want to improve from notebooks?"}],
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
                    "questions": [{"type": "open", "question": "What would you want to improve from notebooks?"}],
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

    def test_get_surveys_errors_on_invalid_token(self):
        self.client.logout()

        with self.assertNumQueries(1):
            response = self._get_surveys(token="invalid_token")
            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert (
                response.json()["detail"]
                == "Project API key invalid. You can find your project API key in your PostHog project settings."
            )

    def test_get_surveys_errors_on_empty_token(self):
        self.client.logout()

        with self.assertNumQueries(0):
            response = self.client.get(f"/api/surveys/")
            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert (
                response.json()["detail"]
                == "API key not provided. You can find your project API key in your PostHog project settings."
            )
