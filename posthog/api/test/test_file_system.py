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
from posthog.models.cohort.cohort import Cohort
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_view_log import FileSystemViewLog
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.link import Link
from posthog.models.surveys.survey import Survey
from posthog.models.web_experiment import WebExperiment
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.early_access_features.backend.models import EarlyAccessFeature
from products.notebooks.backend.models import Notebook


def _ensure_session_cookie(client) -> None:
    session = client.session
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def _create_action_case(testcase: "TestFileSystemViewSetLogging"):
    action = Action.objects.create(team=testcase.team, name="File system action", created_by=testcase.user)
    url = f"/api/projects/{testcase.project.id}/actions/{action.id}/"
    return action, url


def _create_cohort_case(testcase: "TestFileSystemViewSetLogging"):
    cohort = Cohort.objects.create(team=testcase.team, name="File system cohort", created_by=testcase.user)
    url = f"/api/projects/{testcase.project.id}/cohorts/{cohort.id}/"
    return cohort, url


def _create_feature_flag_case(testcase: "TestFileSystemViewSetLogging"):
    flag = FeatureFlag.objects.create(
        team=testcase.team,
        key=f"test-flag-{uuid4().hex}",
        created_by=testcase.user,
    )
    url = f"/api/projects/{testcase.project.id}/feature_flags/{flag.id}/"
    return flag, url


def _create_survey_case(testcase: "TestFileSystemViewSetLogging"):
    survey = Survey.objects.create(
        team=testcase.team,
        name="File system survey",
        type=Survey.SurveyType.POPOVER,
        created_by=testcase.user,
        questions=[],
    )
    url = f"/api/projects/{testcase.project.id}/surveys/{survey.id}/"
    return survey, url


def _create_web_experiment_case(testcase: "TestFileSystemViewSetLogging"):
    flag = FeatureFlag.objects.create(
        team=testcase.team,
        key=f"web-exp-{uuid4().hex}",
        created_by=testcase.user,
    )
    experiment = WebExperiment.objects.create(
        team=testcase.team,
        name="File system web experiment",
        feature_flag=flag,
        created_by=testcase.user,
        type=WebExperiment.ExperimentType.WEB,
    )
    url = f"/api/projects/{testcase.project.id}/web_experiments/{experiment.id}/"
    return experiment, url


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


def _create_hog_function_case(testcase: "TestFileSystemViewSetLogging"):
    hog_function = HogFunction.objects.create(
        team=testcase.team,
        name="File system hog function",
        created_by=testcase.user,
        type=HogFunctionType.SITE_APP,
        hog="return 1",
    )
    url = f"/api/environments/{testcase.team.id}/hog_functions/{hog_function.id}/"
    return hog_function, url


def _create_session_recording_playlist_case(testcase: "TestFileSystemViewSetLogging"):
    playlist = SessionRecordingPlaylist.objects.create(
        team=testcase.team,
        name="File system playlist",
        created_by=testcase.user,
        type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
    )
    url = f"/api/environments/{testcase.team.id}/session_recording_playlists/{playlist.short_id}/"
    return playlist, url


def _create_notebook_case(testcase: "TestFileSystemViewSetLogging"):
    notebook = Notebook.objects.create(team=testcase.team, title="File system notebook", created_by=testcase.user)
    url = f"/api/projects/{testcase.project.id}/notebooks/{notebook.short_id}/"
    return notebook, url


def _create_early_access_feature_case(testcase: "TestFileSystemViewSetLogging"):
    feature = EarlyAccessFeature.objects.create(
        team=testcase.team,
        name="File system feature",
        stage=EarlyAccessFeature.Stage.ALPHA,
    )
    url = f"/api/projects/{testcase.project.id}/early_access_feature/{feature.id}/"
    return feature, url


def _create_link_case(testcase: "TestFileSystemViewSetLogging"):
    link = Link.objects.create(
        team=testcase.team,
        redirect_url="https://posthog.com",
        short_link_domain="phog.gg",
        short_code=f"code-{uuid4().hex[:6]}",
        created_by=testcase.user,
    )
    url = f"/api/projects/{testcase.project.id}/links/{link.id}/"
    return link, url


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

    @parameterized.expand(
        [
            ("action", _create_action_case),
            ("cohort", _create_cohort_case),
            ("survey", _create_survey_case),
            ("web_experiment", _create_web_experiment_case),
            ("hog_function", _create_hog_function_case),
            ("session_recording_playlist", _create_session_recording_playlist_case),
            ("notebook", _create_notebook_case),
            ("early_access_feature", _create_early_access_feature_case),
            ("link", _create_link_case),
        ]
    )
    def test_retrieve_logs_file_system_view(self, _name: str, setup_case) -> None:
        FileSystemViewLog.objects.all().delete()

        try:
            obj, url = setup_case(self)
        except unittest.SkipTest:
            raise

        representation = obj.get_file_system_representation()

        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        log_entry = FileSystemViewLog.objects.get()
        assert log_entry.type == representation.type
        assert log_entry.ref == str(representation.ref)


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
