from datetime import timedelta
from uuid import uuid4

import unittest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils.dateparse import parse_datetime
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.models import Action
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_view_log import FileSystemViewLog


def _ensure_session_cookie(client) -> None:
    session = client.session
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def _create_feature_flag_case(testcase: "TestFileSystemViewSetLogging"):
    flag = FeatureFlag.objects.create(
        team=testcase.team,
        key=f"test-flag-{uuid4().hex}",
        created_by=testcase.user,
    )
    url = f"/api/projects/{testcase.project.id}/feature_flags/{flag.id}/"
    return flag, url


def _create_enterprise_experiment_case(testcase: "TestFileSystemViewSetLogging"):
    if not settings.EE_AVAILABLE:
        raise unittest.SkipTest("Enterprise features unavailable")
    flag = FeatureFlag.objects.create(
        team=testcase.team,
        key=f"exp-{uuid4().hex}",
        created_by=testcase.user,
    )
    experiment = Experiment.objects.create(
        team=testcase.team,
        name="File system experiment",
        feature_flag=flag,
        created_by=testcase.user,
        type=Experiment.ExperimentType.PRODUCT,
    )
    url = f"/api/projects/{testcase.project.id}/experiments/{experiment.id}/"
    return experiment, url


class TestFileSystemOrdering(APIBaseTest):
    def test_order_by_last_viewed_at_desc(self) -> None:
        timestamp = now()

        FileSystem.objects.create(
            team=self.team,
            path="Testing/First",
            depth=2,
            type="insight",
            ref="first",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(days=3),
        )
        FileSystem.objects.create(
            team=self.team,
            path="Testing/Second",
            depth=2,
            type="insight",
            ref="second",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(days=2),
        )
        FileSystem.objects.create(
            team=self.team,
            path="Testing/Third",
            depth=2,
            type="insight",
            ref="third",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(days=1),
        )
        FileSystem.objects.create(
            team=self.team,
            path="Testing/Fourth",
            depth=2,
            type="insight",
            ref="fourth",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(hours=12),
        )

        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="insight",
            ref="first",
            viewed_at=timestamp - timedelta(hours=3),
        )
        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="insight",
            ref="second",
            viewed_at=timestamp - timedelta(hours=1),
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/file_system/",
            {"order_by": "-last_viewed_at", "parent": "Testing", "not_type": "folder"},
        )

        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]
        paths = [item["path"] for item in results]
        assert paths == ["Testing/Second", "Testing/First", "Testing/Fourth", "Testing/Third"]

        assert parse_datetime(results[0]["last_viewed_at"]) == timestamp - timedelta(hours=1)
        assert parse_datetime(results[1]["last_viewed_at"]) == timestamp - timedelta(hours=3)


class TestLogApiFileSystemView(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.factory = APIRequestFactory()
        self.action = Action.objects.create(team=self.team, name="Action", created_by=self.user)

    @parameterized.expand(
        [
            ("anonymous_user", False, True, 0),
            ("missing_cookie", True, False, 0),
            ("authenticated_session", True, True, 1),
        ]
    )
    def test_log_api_file_system_view_conditions(
        self, _name: str, has_user: bool, has_cookie: bool, expected_count: int
    ) -> None:
        FileSystemViewLog.objects.all().delete()
        request = self.factory.get("/api/test/")
        request.user = self.user if has_user else AnonymousUser()
        if has_cookie:
            request.COOKIES[settings.SESSION_COOKIE_NAME] = "session-key"

        log_api_file_system_view(request, self.action)

        assert FileSystemViewLog.objects.count() == expected_count

    def test_log_api_file_system_view_skips_for_impersonated_session(self) -> None:
        FileSystemViewLog.objects.all().delete()
        request = self.factory.get("/api/test/")
        request.user = self.user
        request.COOKIES[settings.SESSION_COOKIE_NAME] = "session-key"

        with patch("posthog.api.file_system.file_system_logging.is_impersonated_session", return_value=True):
            log_api_file_system_view(request, self.action)

        assert FileSystemViewLog.objects.count() == 0


class TestFileSystemViewSetLogging(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _ensure_session_cookie(self.client)


class TestFileSystemLogViewEndpoint(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _ensure_session_cookie(self.client)

    @parameterized.expand(
        [
            ("feature_flag", _create_feature_flag_case, False),
            ("experiment", _create_enterprise_experiment_case, True),
        ]
    )
    def test_log_view_endpoint_creates_entry(self, _name: str, setup_case, requires_ee: bool) -> None:
        if requires_ee and not settings.EE_AVAILABLE:
            raise unittest.SkipTest("Enterprise features unavailable")

        FileSystemViewLog.objects.all().delete()

        obj, _ = setup_case(self)
        representation = obj.get_file_system_representation()

        response = self.client.post(
            f"/api/environments/{self.team.id}/file_system/log_view/",
            {"type": representation.type, "ref": str(representation.ref)},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        log_entry = FileSystemViewLog.objects.get()
        assert log_entry.type == representation.type
        assert log_entry.ref == str(representation.ref)

    def test_log_view_endpoint_rejects_impersonated_session(self) -> None:
        FileSystemViewLog.objects.all().delete()

        obj, _ = _create_feature_flag_case(self)  # type: ignore
        representation = obj.get_file_system_representation()

        with (
            patch("posthog.api.file_system.file_system.is_impersonated_session", return_value=True),
            patch("posthog.api.file_system.file_system.log_api_file_system_view") as mock_logger,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/file_system/log_view/",
                {"type": representation.type, "ref": str(representation.ref)},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_logger.assert_not_called()
        assert FileSystemViewLog.objects.count() == 0

    def test_log_view_endpoint_lists_entries(self) -> None:
        FileSystemViewLog.objects.all().delete()

        earlier = now() - timedelta(hours=1)
        later = now()

        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="scene",
            ref="First",
            viewed_at=earlier,
        )
        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="scene",
            ref="Second",
            viewed_at=later,
        )
        data: dict = {"type": "scene", "limit": 10}
        response = self.client.get(
            f"/api/environments/{self.team.id}/file_system/log_view/",
            data=data,
        )

        assert response.status_code == status.HTTP_200_OK

        payload = response.json()
        assert [entry["ref"] for entry in payload] == ["Second", "First"]
        assert all(entry["type"] == "scene" for entry in payload)
        assert all("viewed_at" in entry for entry in payload)


class TestFileSystemDeletion(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _ensure_session_cookie(self.client)

    def test_deleting_last_copy_soft_deletes_feature_flag(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="delete-flag", created_by=self.user)
        file_entry = FileSystem.objects.get(team=self.team, type="feature_flag", ref=str(flag.id))

        response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{file_entry.id}/",
        )

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["deleted"][0]["mode"] == "soft"
        assert payload["deleted"][0]["type"] == "feature_flag"
        assert payload["deleted"][0]["can_undo"] is True
        assert payload["deleted"][0]["path"] == file_entry.path

        flag.refresh_from_db()
        assert flag.deleted is True

    def test_deleting_non_last_copy_only_removes_entry(self) -> None:
        action = Action.objects.create(team=self.team, name="Delete action", created_by=self.user)
        primary_entry = FileSystem.objects.get(team=self.team, type="action", ref=str(action.id))
        duplicate_entry = FileSystem.objects.create(
            team=self.team,
            path="Unfiled/Actions/Extra copy",
            depth=3,
            type="action",
            ref=str(action.id),
            shortcut=False,
            created_by=self.user,
        )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{duplicate_entry.id}/",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert FileSystem.objects.filter(team=self.team, type="action", ref=str(action.id)).count() == 1
        action.refresh_from_db()
        assert action.deleted is False
        assert FileSystem.objects.filter(id=primary_entry.id).exists()

    def test_deleting_unknown_type_raises_error(self) -> None:
        entry = FileSystem.objects.create(
            team=self.team,
            path="Unfiled/Unknown/Item",
            depth=3,
            type="unknown_type",
            ref="mystery",
            shortcut=False,
            created_by=self.user,
        )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{entry.id}/",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert FileSystem.objects.filter(id=entry.id).exists()

    def test_deleting_folder_with_unknown_type_aborts(self) -> None:
        folder = FileSystem.objects.create(
            team=self.team,
            path="Unfiled/Unknown",
            depth=2,
            type="folder",
            ref=None,
            shortcut=False,
            created_by=self.user,
        )
        FileSystem.objects.create(
            team=self.team,
            path="Unfiled/Unknown/Item",
            depth=3,
            type="unknown_type",
            ref="mystery",
            shortcut=False,
            created_by=self.user,
        )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{folder.id}/",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert FileSystem.objects.filter(team=self.team, path="Unfiled/Unknown/Item").exists()

    def test_undo_delete_restores_feature_flag(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="undo-flag", created_by=self.user)
        file_entry = FileSystem.objects.get(team=self.team, type="feature_flag", ref=str(flag.id))

        delete_response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{file_entry.id}/",
        )

        assert delete_response.status_code == status.HTTP_200_OK
        flag.refresh_from_db()
        assert flag.deleted is True
        assert flag.active is False

        undo_response = self.client.post(
            f"/api/environments/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": "feature_flag", "ref": str(flag.id)}]},
        )

        assert undo_response.status_code == status.HTTP_200_OK
        flag.refresh_from_db()
        assert flag.deleted is False
        assert flag.active is True
        assert FileSystem.objects.filter(team=self.team, type="feature_flag", ref=str(flag.id)).exists()
