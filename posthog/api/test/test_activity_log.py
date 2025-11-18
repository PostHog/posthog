from datetime import timedelta
from typing import Any, Optional

from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory, StepTickTimeFactory
from posthog.test.base import APIBaseTest, QueryMatchingTest

from rest_framework import status

from posthog.models import User


def _feature_flag_json_payload(key: str) -> dict:
    return {
        "key": key,
        "name": "",
        "filters": {
            "groups": [{"properties": [], "rollout_percentage": None}],
            "multivariate": None,
        },
        "deleted": False,
        "active": True,
        "created_by": None,
        "is_simple_flag": False,
        "rollout_percentage": None,
        "ensure_experience_continuity": False,
        "experiment_set": None,
    }


class TestActivityLog(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other_user@posthog.com",
            password="",
        )
        self.third_user = User.objects.create_and_join(
            organization=self.organization,
            email="third_user@posthog.com",
            password="",
        )

        # user one has created 10 insights and 2 flags
        # user two has edited them all
        # user three has edited most of them after that
        self._create_and_edit_things()

        self.client.force_login(self.user)

    def tearDown(self):
        super().tearDown()
        self.client.force_login(self.user)

    def _create_insight(
        self,
        data: dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if "filters" not in data:
            data["filters"] = {"events": [{"id": "$pageview"}]}

        response = self.client.post(f"/api/projects/{team_id}/insights", data=data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json.get("id", None), response_json

    def _create_and_edit_things(self):
        with freeze_time("2023-08-17") as frozen_time:
            # almost every change below will be more than 5 minutes apart
            created_insights = []
            for _ in range(0, 11):
                frozen_time.tick(delta=timedelta(minutes=6))
                insight_id, _ = self._create_insight({})
                created_insights.append(insight_id)

            frozen_time.tick(delta=timedelta(minutes=6))
            flag_one = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                _feature_flag_json_payload("one"),
            ).json()["id"]

            frozen_time.tick(delta=timedelta(minutes=6))
            flag_two = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                _feature_flag_json_payload("two"),
            ).json()["id"]

            frozen_time.tick(delta=timedelta(minutes=6))

            notebook_json = self.client.post(
                f"/api/projects/{self.team.id}/notebooks/",
                {"content": "print('hello world')", "name": "notebook"},
            ).json()

            # other user now edits them
            notebook_version = self._edit_them_all(
                created_insights,
                flag_one,
                flag_two,
                notebook_json["short_id"],
                notebook_json["version"],
                self.other_user,
                frozen_time,
            )
            # third user edits them
            self._edit_them_all(
                created_insights,
                flag_one,
                flag_two,
                notebook_json["short_id"],
                notebook_version,
                self.third_user,
                frozen_time,
            )

    def _edit_them_all(
        self,
        created_insights: list[int],
        flag_one: str,
        flag_two: str,
        notebook_short_id: str,
        notebook_version: int,
        the_user: User,
        frozen_time: FrozenDateTimeFactory | StepTickTimeFactory,
    ) -> int:
        self.client.force_login(the_user)
        for created_insight_id in created_insights[:7]:
            frozen_time.tick(delta=timedelta(minutes=6))
            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{created_insight_id}",
                {"name": f"{created_insight_id}-insight-changed-by-{the_user.id}"},
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            frozen_time.tick(delta=timedelta(minutes=6))
        assert (
            self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_one}",
                {"name": f"one-edited-by-{the_user.id}"},
            ).status_code
            == status.HTTP_200_OK
        )

        frozen_time.tick(delta=timedelta(minutes=6))
        assert (
            self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_two}",
                {"name": f"two-edited-by-{the_user.id}"},
            ).status_code
            == status.HTTP_200_OK
        )

        frozen_time.tick(delta=timedelta(minutes=6))
        # notebooks save while you're typing so, we get multiple activities per edit
        for typed_text in [
            "print",
            "print(",
            "print('hello world again')",
            "print('hello world again from ",
            f"print('hello world again from {the_user.id}')",
        ]:
            frozen_time.tick(delta=timedelta(seconds=5))
            assert (
                self.client.patch(
                    f"/api/projects/{self.team.id}/notebooks/{notebook_short_id}",
                    {"content": typed_text, "version": notebook_version},
                ).status_code
                == status.HTTP_200_OK
            )
            notebook_version = notebook_version + 1

        return notebook_version

    def test_can_list_all_activity(self) -> None:
        res = self.client.get(f"/api/projects/{self.team.id}/activity_log?include_organization_scoped=1")

        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["results"]) == 43

    def test_can_list_all_activity_filtered_by_scope(self) -> None:
        res = self.client.get(f"/api/projects/{self.team.id}/activity_log?scope=FeatureFlag")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["results"]) == 6
        assert [r["scope"] for r in res.json()["results"]] == ["FeatureFlag"] * 6
