from typing import cast

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from posthog.auth import PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication, ProjectSecretAPIKeyUser
from posthog.models import Team, User
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.rate_limit import PersonalApiKeyRateThrottle

from products.ai_observability.backend.api.offline_experiment_access import (
    OfflineEvaluationIngestionBurstThrottle,
    OfflineEvaluationIngestionSustainedThrottle,
    OfflineEvaluationIngestionTeamBurstThrottle,
    OfflineEvaluationIngestionTeamSustainedThrottle,
    OfflineEvaluationReadBurstThrottle,
    OfflineEvaluationReadSustainedThrottle,
    OfflineEvaluationReadTeamBurstThrottle,
    OfflineEvaluationReadTeamSustainedThrottle,
)


class _ProjectView(APIView):
    def __init__(self, team_id: int = 1, parent_team_id: int | None = None) -> None:
        super().__init__()
        self.team_id = team_id
        self.team = Team(id=team_id, parent_team_id=parent_team_id)


class _AuthenticatedRequest(Request):
    _authenticator: BaseAuthentication


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "offline-eval-throttles"}
    }
)
class TestOfflineExperimentThrottles(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.enterContext(patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True))
        self.enterContext(patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False))

    def _request(self, auth_kind: str, identity: int = 1, team_id: int = 1) -> Request:
        request = _AuthenticatedRequest(
            APIRequestFactory().post(f"/api/projects/{team_id}/offline_experiments/", {}, format="json")
        )
        request.user = User(id=identity)
        if auth_kind == "session":
            request._authenticator = SessionAuthentication()
        elif auth_kind == "personal_key":
            auth = PersonalAPIKeyAuthentication()
            auth.personal_api_key_hash = f"personal-key-{identity}"
            request._authenticator = auth
        elif auth_kind == "project_key":
            project_auth = ProjectSecretAPIKeyAuthentication()
            project_auth.project_secret_api_key = ProjectSecretAPIKey(
                id=f"project-key-{identity}", team=Team(id=team_id)
            )
            request.user = cast(User, ProjectSecretAPIKeyUser(project_auth.project_secret_api_key))
            request._authenticator = project_auth
        else:
            raise ValueError(auth_kind)
        return cast(Request, request)

    @parameterized.expand(
        [
            ("burst_session", OfflineEvaluationIngestionBurstThrottle, "session"),
            ("burst_personal_key", OfflineEvaluationIngestionBurstThrottle, "personal_key"),
            ("burst_project_key", OfflineEvaluationIngestionBurstThrottle, "project_key"),
            ("sustained_session", OfflineEvaluationIngestionSustainedThrottle, "session"),
            ("sustained_personal_key", OfflineEvaluationIngestionSustainedThrottle, "personal_key"),
            ("sustained_project_key", OfflineEvaluationIngestionSustainedThrottle, "project_key"),
            ("read_burst_session", OfflineEvaluationReadBurstThrottle, "session"),
            ("read_burst_personal_key", OfflineEvaluationReadBurstThrottle, "personal_key"),
            ("read_sustained_session", OfflineEvaluationReadSustainedThrottle, "session"),
            ("read_sustained_personal_key", OfflineEvaluationReadSustainedThrottle, "personal_key"),
        ]
    )
    def test_each_caller_is_throttled_independently(
        self, _name: str, throttle_class: type[PersonalApiKeyRateThrottle], auth_kind: str
    ) -> None:
        view = _ProjectView()
        with patch.object(throttle_class, "rate", "1/minute"):
            self.assertTrue(throttle_class().allow_request(self._request(auth_kind), view))
            self.assertFalse(throttle_class().allow_request(self._request(auth_kind), view))
            self.assertTrue(throttle_class().allow_request(self._request(auth_kind, identity=2), view))

    @parameterized.expand(
        [
            ("burst", OfflineEvaluationIngestionTeamBurstThrottle, False),
            ("burst_child_environments", OfflineEvaluationIngestionTeamBurstThrottle, True),
            ("sustained", OfflineEvaluationIngestionTeamSustainedThrottle, False),
            ("sustained_child_environments", OfflineEvaluationIngestionTeamSustainedThrottle, True),
            ("read_burst", OfflineEvaluationReadTeamBurstThrottle, False, "session"),
            ("read_burst_child_environments", OfflineEvaluationReadTeamBurstThrottle, True, "personal_key"),
            ("read_sustained", OfflineEvaluationReadTeamSustainedThrottle, False, "session"),
            ("read_sustained_child_environments", OfflineEvaluationReadTeamSustainedThrottle, True, "personal_key"),
        ]
    )
    def test_project_budget_is_shared_across_authentication_methods_and_environments(
        self,
        _name: str,
        throttle_class: type[PersonalApiKeyRateThrottle],
        child_environments: bool,
        last_auth_kind: str = "project_key",
    ) -> None:
        view = _ProjectView()
        personal_key_view = _ProjectView(team_id=2, parent_team_id=1) if child_environments else view
        last_view = _ProjectView(team_id=3, parent_team_id=1) if child_environments else view
        other_view = _ProjectView(team_id=4)
        with patch.object(throttle_class, "rate", "2/minute"):
            self.assertTrue(throttle_class().allow_request(self._request("session"), view))
            self.assertTrue(
                throttle_class().allow_request(
                    self._request("personal_key", team_id=personal_key_view.team_id), personal_key_view
                )
            )
            self.assertFalse(
                throttle_class().allow_request(self._request(last_auth_kind, team_id=last_view.team_id), last_view)
            )
            self.assertTrue(throttle_class().allow_request(self._request(last_auth_kind, team_id=4), other_view))

    @parameterized.expand(
        [
            ("caller_burst", OfflineEvaluationReadBurstThrottle, OfflineEvaluationIngestionBurstThrottle),
            ("caller_sustained", OfflineEvaluationReadSustainedThrottle, OfflineEvaluationIngestionSustainedThrottle),
            ("project_burst", OfflineEvaluationReadTeamBurstThrottle, OfflineEvaluationIngestionTeamBurstThrottle),
            (
                "project_sustained",
                OfflineEvaluationReadTeamSustainedThrottle,
                OfflineEvaluationIngestionTeamSustainedThrottle,
            ),
        ]
    )
    def test_reading_cannot_consume_the_upload_budget(
        self,
        _name: str,
        read_throttle: type[PersonalApiKeyRateThrottle],
        upload_throttle: type[PersonalApiKeyRateThrottle],
    ) -> None:
        view = _ProjectView()
        request = self._request("personal_key")
        with patch.object(read_throttle, "rate", "1/minute"), patch.object(upload_throttle, "rate", "1/minute"):
            self.assertTrue(read_throttle().allow_request(request, view))
            self.assertFalse(read_throttle().allow_request(request, view))
            self.assertTrue(upload_throttle().allow_request(request, view))
            self.assertFalse(upload_throttle().allow_request(request, view))

    def test_unused_api_key_cannot_change_session_bucket(self) -> None:
        view = _ProjectView()
        request = self._request("session")
        with patch.object(OfflineEvaluationIngestionBurstThrottle, "rate", "1/minute"):
            self.assertTrue(OfflineEvaluationIngestionBurstThrottle().allow_request(request, view))
            request.META["HTTP_AUTHORIZATION"] = "Bearer phx_unused_fake_key"
            self.assertFalse(OfflineEvaluationIngestionBurstThrottle().allow_request(request, view))
