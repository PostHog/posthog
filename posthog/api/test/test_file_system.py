from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
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
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.cohort.cohort import Cohort
from posthog.models.dashboard import Dashboard
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_view_log import FileSystemViewLog
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.insight import Insight
from posthog.models.link import Link
from posthog.models.surveys.survey import Survey
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.early_access_features.backend.models import EarlyAccessFeature
from products.notebooks.backend.models import Notebook


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


@dataclass(frozen=True)
class FileSystemActivityCase:
    type_string: str
    scope: str
    create_instance: Callable[[Any], Any]
    ref_getter: Callable[[Any], str]
    item_id_getter: Callable[[Any], str]
    supports_restore: bool = True


FILE_SYSTEM_ACTIVITY_CASES: list[tuple[str, FileSystemActivityCase]] = [
    (
        "dashboard",
        FileSystemActivityCase(
            type_string="dashboard",
            scope="Dashboard",
            create_instance=lambda test: Dashboard.objects.create(
                team=test.team,
                name=f"Dashboard {uuid4().hex}",
                created_by=test.user,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "action",
        FileSystemActivityCase(
            type_string="action",
            scope="Action",
            create_instance=lambda test: Action.objects.create(
                team=test.team,
                name="File system action",
                created_by=test.user,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "feature_flag",
        FileSystemActivityCase(
            type_string="feature_flag",
            scope="FeatureFlag",
            create_instance=lambda test: FeatureFlag.objects.create(
                team=test.team,
                name="File system flag",
                key=f"ff-{uuid4().hex}",
                created_by=test.user,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "experiment",
        FileSystemActivityCase(
            type_string="experiment",
            scope="Experiment",
            create_instance=lambda test: Experiment.objects.create(
                team=test.team,
                name="File system experiment",
                feature_flag=FeatureFlag.objects.create(
                    team=test.team,
                    key=f"exp-ff-{uuid4().hex}",
                    created_by=test.user,
                ),
                created_by=test.user,
                type=Experiment.ExperimentType.PRODUCT,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "insight",
        FileSystemActivityCase(
            type_string="insight",
            scope="Insight",
            create_instance=lambda test: Insight.objects.create(
                team=test.team,
                name="File system insight",
                saved=True,
                created_by=test.user,
                filters={"events": []},
            ),
            ref_getter=lambda instance: instance.short_id,
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "session_recording_playlist",
        FileSystemActivityCase(
            type_string="session_recording_playlist",
            scope="SessionRecordingPlaylist",
            create_instance=lambda test: SessionRecordingPlaylist.objects.create(
                team=test.team,
                name="File system playlist",
                created_by=test.user,
                last_modified_by=test.user,
                type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
            ),
            ref_getter=lambda instance: instance.short_id,
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "cohort",
        FileSystemActivityCase(
            type_string="cohort",
            scope="Cohort",
            create_instance=lambda test: Cohort.objects.create(
                team=test.team,
                name="File system cohort",
                filters={"properties": []},
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "hog_function",
        FileSystemActivityCase(
            type_string=f"hog_function/{HogFunctionType.DESTINATION}",
            scope="HogFunction",
            create_instance=lambda test: HogFunction.objects.create(
                team=test.team,
                name="File system hog function",
                type=HogFunctionType.DESTINATION,
                hog="return []",
                created_by=test.user,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
        ),
    ),
    (
        "notebook",
        FileSystemActivityCase(
            type_string="notebook",
            scope="Notebook",
            create_instance=lambda test: Notebook.objects.create(
                team=test.team,
                title="File system notebook",
                created_by=test.user,
                last_modified_by=test.user,
            ),
            ref_getter=lambda instance: str(instance.short_id),
            item_id_getter=lambda instance: str(instance.short_id),
        ),
    ),
    (
        "link",
        FileSystemActivityCase(
            type_string="link",
            scope="Link",
            create_instance=lambda test: Link.objects.create(
                team=test.team,
                redirect_url="https://posthog.com",
                short_link_domain="hog.gg",
                short_code=f"lnk-{uuid4().hex[:8]}",
                description="File system link",
                created_by=test.user,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
            supports_restore=False,
        ),
    ),
    (
        "survey",
        FileSystemActivityCase(
            type_string="survey",
            scope="Survey",
            create_instance=lambda test: Survey.objects.create(
                team=test.team,
                name=f"File system survey {uuid4().hex}",
                type=Survey.SurveyType.POPOVER,
                questions=[{"id": str(uuid4()), "type": "open", "question": "How are you?"}],
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
            supports_restore=False,
        ),
    ),
    (
        "early_access_feature",
        FileSystemActivityCase(
            type_string="early_access_feature",
            scope="EarlyAccessFeature",
            create_instance=lambda test: EarlyAccessFeature.objects.create(
                team=test.team,
                name="File system EAF",
                stage=EarlyAccessFeature.Stage.DRAFT,
            ),
            ref_getter=lambda instance: str(instance.id),
            item_id_getter=lambda instance: str(instance.id),
            supports_restore=False,
        ),
    ),
]

RESTORABLE_FILE_SYSTEM_CASES = [case for case in FILE_SYSTEM_ACTIVITY_CASES if case[1].supports_restore]


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


class TestFileSystemSearchNameOnly(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/file_system/"
        FileSystem.objects.create(
            team=self.team,
            path="AlphaParent",
            depth=1,
            type="folder",
            ref="alpha-parent",
            shortcut=False,
            created_by=self.user,
        )
        FileSystem.objects.create(
            team=self.team,
            path="AlphaParent/Child",
            depth=2,
            type="folder",
            ref="alpha-child",
            shortcut=False,
            created_by=self.user,
        )

    def test_default_search_matches_parent_segments(self) -> None:
        response = self.client.get(self.url, {"search": "alphaparent", "type": "folder"})
        assert response.status_code == status.HTTP_200_OK
        paths = [item["path"] for item in response.json()["results"]]
        assert "AlphaParent" in paths
        assert "AlphaParent/Child" in paths

    def test_search_name_only_limits_to_basename(self) -> None:
        response = self.client.get(
            self.url,
            {"search": "alphaparent", "type": "folder", "search_name_only": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        paths = [item["path"] for item in response.json()["results"]]
        assert "AlphaParent" in paths
        assert "AlphaParent/Child" not in paths


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
            patch("posthog.decorators.is_impersonated_session", return_value=True),
            patch("posthog.api.file_system.file_system_logging.log_api_file_system_view") as mock_logger,
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

    def _assert_activity_log_count(self, scope: str, activity: str, item_id: str, expected: int = 1) -> None:
        count = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope=scope,
            activity=activity,
            item_id=str(item_id),
        ).count()
        assert count == expected, f"Expected {expected} '{activity}' log entries for {scope} {item_id}, found {count}"

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
        assert FileSystem.objects.filter(team=self.team, type="feature_flag", ref=str(flag.id)).exists()
        assert flag.active is True
        assert flag.deleted is False  # type: ignore

    def test_undo_delete_restores_original_path(self) -> None:
        flag = FeatureFlag(team=self.team, key="undo-path-flag", created_by=self.user)
        flag._create_in_folder = "Restored/Flags"
        flag.save()
        file_entry = FileSystem.objects.get(team=self.team, type="feature_flag", ref=str(flag.id))
        original_path = file_entry.path

        delete_response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{file_entry.id}/",
        )

        assert delete_response.status_code == status.HTTP_200_OK
        assert not FileSystem.objects.filter(team=self.team, type="feature_flag", ref=str(flag.id)).exists()

        undo_response = self.client.post(
            f"/api/environments/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": "feature_flag", "ref": str(flag.id), "path": original_path}]},
        )

        assert undo_response.status_code == status.HTTP_200_OK
        restored_entry = FileSystem.objects.get(team=self.team, type="feature_flag", ref=str(flag.id))
        assert restored_entry.path == original_path

    @parameterized.expand(FILE_SYSTEM_ACTIVITY_CASES)
    def test_file_system_delete_emits_single_activity_log(self, _name: str, case: FileSystemActivityCase) -> None:
        ActivityLog.objects.all().delete()
        instance = case.create_instance(self)
        ActivityLog.objects.all().delete()

        ref = case.ref_getter(instance)
        item_id = case.item_id_getter(instance)
        entry = FileSystem.objects.get(team=self.team, type=case.type_string, ref=ref)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{entry.id}/",
        )

        assert response.status_code == status.HTTP_200_OK
        self._assert_activity_log_count(case.scope, "deleted", item_id)

    @parameterized.expand(RESTORABLE_FILE_SYSTEM_CASES)
    def test_file_system_restore_emits_single_activity_log(self, _name: str, case: FileSystemActivityCase) -> None:
        ActivityLog.objects.all().delete()
        instance = case.create_instance(self)
        ActivityLog.objects.all().delete()

        ref = case.ref_getter(instance)
        item_id = case.item_id_getter(instance)
        entry = FileSystem.objects.get(team=self.team, type=case.type_string, ref=ref)

        delete_response = self.client.delete(
            f"/api/environments/{self.team.id}/file_system/{entry.id}/",
        )

        assert delete_response.status_code == status.HTTP_200_OK

        undo_response = self.client.post(
            f"/api/environments/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": case.type_string, "ref": ref}]},
        )

        assert undo_response.status_code == status.HTTP_200_OK
        self._assert_activity_log_count(case.scope, "deleted", item_id)
        self._assert_activity_log_count(case.scope, "restored", item_id)

    def test_insight_restore_activity_log_includes_name(self) -> None:
        ActivityLog.objects.all().delete()
        insight = Insight.objects.create(
            team=self.team,
            name="File system insight",
            saved=True,
            created_by=self.user,
            filters={"events": []},
        )
        entry = FileSystem.objects.get(team=self.team, type="insight", ref=insight.short_id)

        self.client.delete(f"/api/environments/{self.team.id}/file_system/{entry.id}/")
        self.client.post(
            f"/api/environments/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": "insight", "ref": insight.short_id}]},
        )

        log = ActivityLog.objects.get(scope="Insight", activity="restored", item_id=str(insight.id))
        assert log.detail["name"] == "File system insight"  # type: ignore

    def test_cohort_restore_activity_log_includes_name(self) -> None:
        ActivityLog.objects.all().delete()
        cohort = Cohort.objects.create(team=self.team, name="File system cohort", filters={"properties": []})
        entry = FileSystem.objects.get(team=self.team, type="cohort", ref=str(cohort.id))

        self.client.delete(f"/api/environments/{self.team.id}/file_system/{entry.id}/")
        self.client.post(
            f"/api/environments/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": "cohort", "ref": str(cohort.id)}]},
        )

        log = ActivityLog.objects.get(scope="Cohort", activity="restored", item_id=str(cohort.id))
        assert log.detail["name"] == "File system cohort"  # type: ignore
