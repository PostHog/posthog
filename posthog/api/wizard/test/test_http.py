import json
from datetime import timedelta
from decimal import Decimal

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.llm.wizard_blocklist import WIZARD_BLOCKED_DETAIL
from posthog.llm.wizard_gateway_token import WizardGatewayMintError
from posthog.models import Organization, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle, refund_wizard_mint, reserve_wizard_mint


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
class SetupWizardCloudRunTests(APIBaseTest):
    CLOUD_RUN_URL = "/api/wizard/cloud_run"

    @patch("posthog.api.wizard.http.wizard_identity_blocked", return_value=True)
    def test_a_blocked_identity_cannot_start_a_cloud_run(self, mock_blocked):
        # The sandbox mints its own gateway token.
        response = self.client.post(
            self.CLOUD_RUN_URL,
            {"project_id": self.team.project_id, "repository": "PostHog/posthog"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.json()["detail"] == WIZARD_BLOCKED_DETAIL
        assert mock_blocked.call_args.kwargs["surface"] == "cloud_run"

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="")
    def test_returns_404_when_feature_not_configured(self):
        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_creates_run_and_returns_ids(self, mock_create):
        mock_create.return_value = MagicMock(task_id="task-uuid", latest_run=MagicMock(id="run-uuid", status="queued"))

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app", "branch": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"task_id": "task-uuid", "run_id": "run-uuid", "status": "queued"}
        assert mock_create.call_count == 1
        kwargs = mock_create.call_args.kwargs
        assert kwargs["repository"] == "acme/app"
        assert kwargs["user_id"] == self.user.id
        assert kwargs["branch"] is None
        assert kwargs["team"].id == self.team.id

    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_rejects_invalid_repository_format(self, mock_create):
        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "not-a-repo"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_create.assert_not_called()

    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_rejects_personal_api_key_auth(self, mock_create):
        # Cloud run is a UI/session-only action — an API token must not be able to start a run,
        # even with a broad scope, since the project visibility check below wouldn't honor token scopes.
        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Test API Key",
            secure_value=hash_key_value(api_key_value),
            scopes=["*"],
        )
        self.client.logout()

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
            headers={"authorization": f"Bearer {api_key_value}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_create.assert_not_called()

    def test_rejects_project_without_access(self):
        other_org = Organization.objects.create(name="Other Cloud Run Org")
        other_user = User.objects.create_and_join(other_org, "other-cloud-run@example.com", None)
        self.client.force_login(other_user)

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.facade.api.recent_wizard_cloud_run_times")
    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_throttles_when_quota_counting_runs_reports_the_cap(self, mock_create, mock_run_times):
        # Wiring guard for the outcome-aware throttles: the endpoint must consult the facade's
        # run count (the exclusion behavior itself is covered in the tasks product's facade tests).
        mock_run_times.return_value = [timezone.now() - timedelta(minutes=5), timezone.now() - timedelta(minutes=1)]

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        mock_create.assert_not_called()

    @patch("posthog.api.wizard.http.WIZARD_CLOUD_RUN_DAILY_ATTEMPT_CAP", 2)
    @patch("products.tasks.backend.facade.api.recent_wizard_cloud_run_times")
    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_attempt_reservation_is_a_hard_ceiling_regardless_of_run_outcome(self, mock_create, mock_run_times):
        # The DB-counted throttles ignore failed/cancelled runs, so the atomic reservation is
        # the only thing bounding a start-fail or start-cancel loop.
        mock_run_times.return_value = []
        mock_create.return_value = MagicMock(task_id="task-uuid", latest_run=MagicMock(id="run-uuid", status="queued"))

        for _ in range(2):
            response = self.client.post(
                self.CLOUD_RUN_URL,
                data={"project_id": self.team.id, "repository": "acme/app"},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK, response.content

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert mock_create.call_count == 2

    def tearDown(self):
        super().tearDown()
        cache.clear()  # Clears out all DRF throttle data


class SetupWizardGatewayTokenThrottleTests(APIBaseTest):
    def tearDown(self):
        super().tearDown()
        cache.clear()

    def test_key_ignores_a_caller_supplied_forwarded_for(self):
        from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle

        throttle = SetupWizardGatewayTokenRateThrottle()
        factory = APIRequestFactory()

        first = factory.post("/api/wizard/gateway_token", HTTP_X_FORWARDED_FOR="1.2.3.4")
        second = factory.post("/api/wizard/gateway_token", HTTP_X_FORWARDED_FOR="5.6.7.8, 9.9.9.9")

        # Same untrusted origin, two different forwarded headers: the bucket
        # must not move, or the cap is bypassed by rotating the header.
        assert throttle.get_cache_key(Request(first), None) == throttle.get_cache_key(Request(second), None)

    @patch("posthog.rate_limit.OAuthAccessTokenAuthentication")
    def test_key_follows_the_authenticated_user(self, mock_authentication):
        from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle

        throttle = SetupWizardGatewayTokenRateThrottle()
        factory = APIRequestFactory()
        mock_authentication.return_value.authenticate.return_value = (self.user, None)

        keyed = throttle.get_cache_key(Request(factory.post("/api/wizard/gateway_token")), None)
        mock_authentication.return_value.authenticate.return_value = None
        anonymous = throttle.get_cache_key(Request(factory.post("/api/wizard/gateway_token")), None)

        assert keyed != anonymous


@override_settings(
    WIZARD_GATEWAY_MINT_KEY="phs_wizard_mint",
    WIZARD_GATEWAY_URL="https://ai-gateway.us.posthog.com",
    WIZARD_GATEWAY_CLIENT_IDS=["wizard-client-id"],
    WIZARD_GATEWAY_PROGRAM_IDS=["integration"],
)
class SetupWizardGatewayTokenTests(APIBaseTest):
    GATEWAY_TOKEN_URL = "/api/wizard/gateway_token"

    MINTED = {"token": "phe_test_token", "expires_at": "2026-08-22T00:00:00Z", "cap_usd": "50"}

    def setUp(self):
        super().setUp()
        # Keeps the SDK off the network; a test sets a payload to opt in.
        payload_patch = patch(
            "posthog.llm.wizard_gateway_token.posthoganalytics.get_feature_flag_payload", return_value=None
        )
        self.mock_limit_payload = payload_patch.start()
        self.addCleanup(payload_patch.stop)
        # Patched at the endpoint's seam: the feature_enabled patches below land on
        # the shared module object, so an SDK-level patch would read the rollout
        # flag's value as a ban.
        blocklist_patch = patch("posthog.api.wizard.http.wizard_identity_blocked", return_value=False)
        self.mock_blocklist = blocklist_patch.start()
        self.addCleanup(blocklist_patch.stop)

    def tearDown(self):
        super().tearDown()
        cache.clear()  # Clears out all DRF throttle data

    def _mock_oauth(self, mock_authentication, scope=None, scoped_teams=None, client_id="wizard-client-id"):
        mock_authenticator = mock_authentication.return_value
        mock_authenticator.authenticate.return_value = (self.user, None)
        mock_authenticator.access_token.scope = "llm_gateway:read" if scope is None else scope
        mock_authenticator.access_token.scoped_teams = scoped_teams if scoped_teams is not None else [self.team.id]
        mock_authenticator.access_token.application.client_id = client_id
        return mock_authenticator

    @override_settings(WIZARD_GATEWAY_MINT_KEY="")
    def test_unconfigured_is_404(self):
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_mints_for_scoped_oauth_token(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["token"] == "phe_test_token"
        assert body["expires_at"] == self.MINTED["expires_at"]
        assert body["gateway_url"] == "https://ai-gateway.us.posthog.com"
        assert body["team_id"] == self.team.id
        assert mock_mint.call_args.kwargs == {
            "obo": str(self.team.organization_id),
            "user": str(self.user.distinct_id),
            "product": "wizard:integration",
            "cap_usd": None,
        }

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_flag_off_is_404(self, mock_authentication, mock_flag, mock_authorized):
        self._mock_oauth(mock_authentication)
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_blocked_identity_is_403_and_never_mints(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        # 403 rather than 404, which the CLI reads as "stay on legacy".
        self._mock_oauth(mock_authentication)
        self.mock_blocklist.return_value = True

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.json()["detail"] == WIZARD_BLOCKED_DETAIL
        mock_mint.assert_not_called()

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_ban_outranks_the_rollout_gate(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        # Not-rolled-out answers 404 and downgrades to legacy, so the ban has to
        # land first whatever the rollout says.
        self._mock_oauth(mock_authentication)
        self.mock_blocklist.return_value = True

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_the_ban_is_asked_about_the_authenticated_identity(
        self, mock_authentication, mock_flag, mock_mint, mock_authorized
    ):
        self._mock_oauth(mock_authentication)

        self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert self.mock_blocklist.call_args.kwargs == {
            "distinct_id": str(self.user.distinct_id),
            "email": self.user.email,
            "user_uuid": str(self.user.uuid),
            "organization_ids": [str(self.team.organization_id)],
            "team_ids": [self.team.id],
            "surface": "gateway_token",
        }

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_ban_is_counted(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)
        self.mock_blocklist.return_value = True
        before = _gateway_token_outcome("blocked")

        self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert _gateway_token_outcome("blocked") == before + 1

    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_missing_gateway_scope_is_401(self, mock_authentication):
        # "*" must not subsume the privileged scope.
        self._mock_oauth(mock_authentication, scope="*")
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_token_from_another_application_is_401(self, mock_authentication, mock_authorized):
        self._mock_oauth(mock_authentication, client_id="sandbox-client-id")
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=False)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_revoked_project_access_is_403(self, mock_authentication, mock_flag, mock_authorized):
        self._mock_oauth(mock_authentication)
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_request_is_rejected(self):
        # No authenticator mock: the real one must refuse a request with no
        # bearer, on a viewset whose permission_classes is empty.
        self.client.logout()
        response = self.client.post(self.GATEWAY_TOKEN_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_session_cookie_alone_is_rejected(self):
        # APIBaseTest leaves a logged-in session; it must not authorize a mint.
        response = self.client.post(self.GATEWAY_TOKEN_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_multi_team_scope_is_400(self, mock_authentication):
        self._mock_oauth(mock_authentication, scoped_teams=[self.team.id, self.team.id + 1])
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch(
        "posthog.api.wizard.http.mint_wizard_gateway_token",
        side_effect=WizardGatewayMintError("refused"),
    )
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_mint_failure_is_503(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)
        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @override_settings(DEBUG=False)
    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_limit_override_raises_the_daily_ceiling(
        self, mock_authentication, mock_flag, mock_authorized, mock_mint, mock_key
    ):
        self._mock_oauth(mock_authentication)
        self.mock_limit_payload.return_value = {"mints_per_day": 7}

        for _ in range(7):
            ok = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )
            assert ok.status_code == status.HTTP_201_CREATED, ok.content
        refused = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert mock_mint.call_count == 7

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_limit_override_cap_reaches_the_mint(self, mock_authentication, mock_flag, mock_authorized, mock_mint):
        self._mock_oauth(mock_authentication)
        self.mock_limit_payload.return_value = json.dumps({"cap_usd": "30"})

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert mock_mint.call_args.kwargs["cap_usd"] == Decimal("30.000000")
        self.mock_limit_payload.assert_called_once_with(
            "wizard-gateway-limit-override",
            str(self.user.distinct_id),
            person_properties={
                "email": self.user.email,
                "organization_id": str(self.team.organization_id),
                "team_id": str(self.team.id),
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_flag_outage_keeps_the_default_limits(self, mock_authentication, mock_flag, mock_authorized, mock_mint):
        self._mock_oauth(mock_authentication)
        self.mock_limit_payload.side_effect = RuntimeError("flags unavailable")

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert mock_mint.call_args.kwargs["cap_usd"] is None

    def _reserved_counter_value(self, key="refund-test-key"):
        """The live value of the reservation counter for a pinned cache key."""
        import time

        from django.core.cache import cache as django_cache

        from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle

        window = int(time.time()) // SetupWizardGatewayTokenRateThrottle().duration
        return django_cache.get(f"{key}:{window}")

    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_failure_that_issued_no_token_returns_the_slot(
        self, mock_authentication, mock_flag, mock_authorized, mock_key
    ):
        # Nothing below the helper's unit tests covers deleting or inverting this.
        self._mock_oauth(mock_authentication)
        with patch(
            "posthog.api.wizard.http.mint_wizard_gateway_token",
            side_effect=WizardGatewayMintError("refused", token_may_exist=False),
        ):
            response = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert self._reserved_counter_value() == 0

    @override_settings(DEBUG=False)
    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_induced_failures_cannot_buy_extra_tokens(self, mock_authentication, mock_flag, mock_authorized, mock_key):
        """The counter must equal the tokens actually issued, however many failures ran.

        The refund exists so an outage does not burn a user's quota, which invites
        the mirror question: induce failures on purpose and keep the slot each time.
        That is only safe while a refund is impossible on any path that hands back a
        token, so the ceiling has to bind on issued tokens rather than on attempts.
        """
        self._mock_oauth(mock_authentication)

        with patch(
            "posthog.api.wizard.http.mint_wizard_gateway_token",
            side_effect=WizardGatewayMintError("unreachable", token_may_exist=False),
        ):
            for _ in range(20):
                failed = self.client.post(
                    self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
                )
                assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

        assert self._reserved_counter_value() == 0

        with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=self.MINTED) as mock_mint:
            for _ in range(5):
                ok = self.client.post(
                    self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
                )
                assert ok.status_code == status.HTTP_201_CREATED
            # The ceiling counts issued tokens, so the 20 refunded failures bought
            # nothing: the sixth mint is refused even though 25 requests preceded it.
            refused = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )

        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert mock_mint.call_count == 5
        assert self._reserved_counter_value() == 6

    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_failure_that_may_have_issued_a_token_keeps_the_slot(
        self, mock_authentication, mock_flag, mock_authorized, mock_key
    ):
        # The paired negative: the gateway may hold this token.
        self._mock_oauth(mock_authentication)
        with patch(
            "posthog.api.wizard.http.mint_wizard_gateway_token",
            side_effect=WizardGatewayMintError("unreadable", token_may_exist=True),
        ):
            response = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert self._reserved_counter_value() == 1

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_unlisted_program_is_refused(self, mock_authentication, mock_flag, mock_authorized, mock_mint):
        self._mock_oauth(mock_authentication)
        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "invented"}, headers={"authorization": "Bearer pha_test"}
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_mint.assert_not_called()

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_missing_program_is_refused(self, mock_authentication, mock_flag, mock_authorized, mock_mint):
        self._mock_oauth(mock_authentication)
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_mint.assert_not_called()

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_non_string_program_is_refused_not_a_500(
        self, mock_authentication, mock_flag, mock_authorized, mock_mint
    ):
        # An unhashable value raises on the set membership, inside a throttle that
        # runs before authentication.
        self._mock_oauth(mock_authentication)
        response = self.client.post(
            self.GATEWAY_TOKEN_URL,
            data=json.dumps({"program": ["integration"]}),
            content_type="application/json",
            headers={"authorization": "Bearer pha_test"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_mint.assert_not_called()

    @override_settings(DEBUG=False)
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_throttled_mint_is_counted(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)
        before = _gateway_token_outcome("throttled")

        for _ in range(5):
            self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )
        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert _gateway_token_outcome("throttled") == before + 1

    def test_an_unresolvable_bearer_is_counted(self):
        before = _gateway_token_outcome("invalid_token")

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_unknown"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert _gateway_token_outcome("invalid_token") == before + 1


def _gateway_token_outcome(outcome: str) -> float:
    """Current value of one outcome counter. An unrecorded label reads as zero."""
    return REGISTRY.get_sample_value("posthog_wizard_gateway_token_requests_total", {"outcome": outcome}) or 0.0


class TestReserveWizardMint:
    """The ceiling is atomic and sits on the mint, not on arrival."""

    @pytest.fixture(autouse=True)
    def _settings(self):
        with override_settings(WIZARD_GATEWAY_PROGRAM_IDS=["integration"], DEBUG=False):
            yield

    def _request(self):
        factory = APIRequestFactory()
        return Request(factory.post("/api/wizard/gateway_token", {"program": "integration"}))

    def test_the_sixth_reservation_in_a_window_is_refused(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            for _ in range(5):
                reserve_wizard_mint(req, None)
            with pytest.raises(Throttled):
                reserve_wizard_mint(req, None)

    def test_the_reservation_returns_the_counter_it_charged(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            counter = reserve_wizard_mint(req, None)
        assert counter is not None
        assert counter.startswith("k:")
        assert django_cache.get(counter) == 1

    def test_a_refund_returns_the_slot_to_that_counter(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            counter = reserve_wizard_mint(req, None)
            refund_wizard_mint(counter)
            # The refunded slot is spendable again rather than merely not charged.
            for _ in range(5):
                reserve_wizard_mint(req, None)
            with pytest.raises(Throttled):
                reserve_wizard_mint(req, None)

    def test_a_vanished_key_is_re_established_so_its_counter_is_refundable(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            with patch("posthog.rate_limit.cache.incr", side_effect=ValueError("no key")):
                counter = reserve_wizard_mint(req, None)

        assert counter is not None
        assert django_cache.get(counter) == 1
        refund_wizard_mint(counter)
        assert django_cache.get(counter) == 0

    def test_a_refund_without_a_counter_is_a_no_op(self):
        refund_wizard_mint(None)

    def test_a_cache_failure_fails_open(self):
        # Load-shedding posture: the per-token cap and the wallet also bound this,
        # and a Redis blip must not turn a minted token into a 500.
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", side_effect=RuntimeError("redis down")):
            reserve_wizard_mint(req, None)
