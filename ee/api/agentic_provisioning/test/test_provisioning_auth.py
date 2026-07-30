import json

from unittest.mock import MagicMock, patch

from django.core.cache import cache as real_cache

from parameterized import parameterized

from posthog.api.oauth.cimd import _blocked_key, _cache_key
from posthog.models.oauth import OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User

from ee.api.agentic_provisioning.authentication import ProvisioningAuthentication
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase

WIZARD_CLIENT_ID = "test-wizard-client"


class TestProvisioningAuthentication(ProvisioningTestBase):
    def setUp(self):
        super().setUp()

        OAuthApplication.objects.filter(client_id=WIZARD_CLIENT_ID).delete()
        self.wizard_app = OAuthApplication.objects.create(
            client_id=WIZARD_CLIENT_ID,
            name="PostHog Wizard",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

    def _wizard_account_request(self, request_id: str, email: str, challenge: str):
        return self._post_api(
            "/api/agentic/provisioning/account_requests",
            {
                "id": request_id,
                "email": email,
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

    def _exchange_code(self, code: str, verifier: str):
        return self.client.post(
            "/api/agentic/oauth/token",
            data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        )

    # --- Bearer identification ---

    def test_bearer_partner_identified_by_token(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/account_requests",
            {"id": "req_bearer", "email": "bearer-new-user@example.com"},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    def test_inactive_bearer_partner_rejected(self):
        token = self._get_bearer_token()
        self.partner.provisioning_active = False
        self.partner.save(update_fields=["provisioning_active"])

        res = self._post_with_bearer(
            "/api/agentic/provisioning/account_requests",
            {"id": "req_inactive_bearer", "email": "inactive-bearer@example.com"},
            token=token,
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    # --- HMAC partners are fail-closed ---

    def test_hmac_partner_can_no_longer_authenticate(self):
        OAuthApplication.objects.create(
            client_id="legacy-hmac-partner",
            name="Legacy HMAC Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://legacy.example.com/callback",
            algorithm="RS256",
            provisioning_auth_method="hmac",
            provisioning_partner_type="stripe",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        res = self._post_api(
            "/api/agentic/provisioning/account_requests",
            {"id": "req_hmac", "email": "hmac-partner@example.com", "client_id": "legacy-hmac-partner"},
            HTTP_STRIPE_SIGNATURE="t=1234567890,v1=deadbeef",
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    # --- PKCE flow ---

    def test_pkce_wizard_new_user_full_flow(self):
        verifier, challenge = self._pkce_pair()

        res = self._wizard_account_request("req_wizard_1", "wizard-user@example.com", challenge)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        code = data["oauth"]["code"]

        res = self._exchange_code(code, verifier)
        assert res.status_code == 200
        tokens = res.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["expires_in"] == 3600

        res = self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=tokens["access_token"])
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert "api_key" in res.json()["complete"]["access_configuration"]

    @parameterized.expand(
        [
            ("wrong_verifier", "wrong_verifier_value", 400),
            ("missing_verifier", "", 401),
        ]
    )
    def test_pkce_code_exchange_requires_matching_verifier(self, _name, verifier, expected_status):
        _, challenge = self._pkce_pair()

        res = self._wizard_account_request("req_bad_pkce", "bad-pkce@example.com", challenge)
        code = res.json()["oauth"]["code"]

        res = self._exchange_code(code, verifier)
        assert res.status_code == expected_status
        if expected_status == 400:
            assert res.json()["error"] == "invalid_grant"

    # --- can_create_accounts enforcement ---

    def test_partner_without_can_create_accounts_rejected(self):
        OAuthApplication.objects.create(
            name="Disabled Partner",
            client_id="disabled-partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            provisioning_auth_method="pkce",
            provisioning_partner_type="disabled",
            provisioning_active=True,
            provisioning_can_create_accounts=False,
        )

        res = self._post_api(
            "/api/agentic/provisioning/account_requests",
            {"id": "req_disabled", "email": "disabled@example.com", "client_id": "disabled-partner"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"

    # --- Org naming ---

    def test_wizard_org_named_with_partner_type(self):
        _, challenge = self._pkce_pair()
        email = "org-name-test@example.com"

        self._wizard_account_request("req_org_name", email, challenge)

        user = User.objects.get(email=email)
        membership = user.organization_memberships.first()
        assert membership is not None
        org = membership.organization
        assert org.name == f"Wizard ({email})"

    # --- PAT scopes ---

    def test_default_off_app_mints_no_provisioned_pat(self):
        verifier, challenge = self._pkce_pair()
        email = "pat-test@example.com"

        res = self._wizard_account_request("req_pat", email, challenge)
        code = res.json()["oauth"]["code"]
        token = self._exchange_code(code, verifier).json()["access_token"]

        self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=token)

        user = User.objects.get(email=email)
        # The wizard app does not set provisioning_issues_personal_api_key, so no PAT is minted.
        pat = PersonalAPIKey.objects.filter(user=user).first()
        assert pat is None

    # --- is_active kill switch ---

    def test_inactive_pkce_partner_rejected(self):
        self.wizard_app.provisioning_active = False
        self.wizard_app.save(update_fields=["provisioning_active"])

        _, challenge = self._pkce_pair()
        res = self._wizard_account_request("req_inactive_pkce", "inactive-pkce@example.com", challenge)
        assert res.status_code == 401

    # --- can_provision_resources enforcement ---

    def test_partner_without_can_provision_resources_rejected(self):
        token = self._get_bearer_token()

        self.partner.provisioning_can_provision_resources = False
        self.partner.save(update_fields=["provisioning_can_provision_resources"])

        res = self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=token)
        assert res.status_code == 403

    # --- CIMD URL-based PKCE identification ---

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_pkce_partner_identified_by_cimd_url(self, mock_refresh):
        cimd_url = "https://example.com/api/oauth/wizard/client-metadata"
        OAuthApplication.objects.create(
            name="CIMD Wizard",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=cimd_url,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        _, challenge = self._pkce_pair()
        res = self._post_api(
            "/api/agentic/provisioning/account_requests",
            {
                "id": "req_cimd_pkce",
                "email": "cimd-wizard@example.com",
                "client_id": cimd_url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_cimd_url_inactive_partner_rejected(self, mock_refresh):
        cimd_url = "https://example.com/api/oauth/wizard/client-metadata-inactive"
        OAuthApplication.objects.create(
            name="Inactive CIMD Wizard",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=cimd_url,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=False,
            provisioning_can_create_accounts=True,
        )

        _, challenge = self._pkce_pair()
        res = self._post_api(
            "/api/agentic/provisioning/account_requests",
            {
                "id": "req_cimd_inactive",
                "email": "cimd-inactive@example.com",
                "client_id": cimd_url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert res.status_code == 401

    @parameterized.expand(
        [
            ("stale_cache_fires_refresh", False, 1),
            ("fresh_cache_skips_refresh", True, 0),
        ]
    )
    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_cimd_provisioning_partner_refreshes_metadata_only_when_stale(
        self, _name, cache_is_fresh, expected_delay_calls, mock_refresh
    ):
        cimd_url = "https://example.com/api/oauth/wizard/refresh-on-auth"
        cimd_app = OAuthApplication.objects.create(
            name="CIMD Wizard Refresh",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=cimd_url,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )
        self.addCleanup(real_cache.delete, _cache_key(cimd_url))
        # _identify_pkce_partner warms the blocklist cache with a 1-year TTL; clear it too.
        self.addCleanup(real_cache.delete, _blocked_key(cimd_url))

        if cache_is_fresh:
            real_cache.set(_cache_key(cimd_url), True, timeout=300)
        else:
            real_cache.delete(_cache_key(cimd_url))

        partner = ProvisioningAuthentication()._identify_pkce_partner(cimd_url)

        assert partner == cimd_app
        assert mock_refresh.delay.call_count == expected_delay_calls
        if expected_delay_calls:
            mock_refresh.delay.assert_called_once_with(cimd_url)

    # --- PKCE code_challenge_method validation ---

    def test_plain_code_challenge_method_rejected(self):
        res = self._post_api(
            "/api/agentic/provisioning/account_requests",
            {
                "id": "req_plain",
                "email": "plain-pkce@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": "some_challenge",
                "code_challenge_method": "plain",
            },
        )
        assert res.status_code == 400
        assert "S256" in res.json()["error"]["message"]


CIMD_PROV_URL = "https://partner.example.com/.well-known/oauth-client-metadata.json"


def _make_cimd_metadata(url: str = CIMD_PROV_URL, **overrides) -> dict:
    metadata = {
        "client_id": url,
        "client_name": "Partner App",
        "redirect_uris": ["http://127.0.0.1:3000/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    metadata.update(overrides)
    return metadata


def _cimd_mock_response(metadata: dict | None, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.close = MagicMock()
    body = json.dumps(metadata).encode() if metadata is not None else b""
    resp.iter_content = MagicMock(return_value=iter([body]))
    return resp


@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
class TestCimdProvisioningAutoRegistration(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        OAuthApplication.objects.filter(cimd_metadata_url=CIMD_PROV_URL).delete()
        real_cache.clear()

    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_new_cimd_partner_returns_202_and_kicks_off_registration(self, mock_task, _url_mock):
        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_auto",
                "email": "cimd-auto@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )

        assert res.status_code == 202
        assert res.json()["type"] == "registering"
        assert res.json()["retry_after"] == 5
        mock_task.delay.assert_called_once_with(CIMD_PROV_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_new_cimd_partner_succeeds_after_background_registration(self, mock_get, _url_mock):
        mock_get.return_value = _cimd_mock_response(_make_cimd_metadata())

        from posthog.api.oauth.cimd import register_cimd_provisioning_application_task

        register_cimd_provisioning_application_task(CIMD_PROV_URL)

        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        assert app.is_cimd_client
        assert app.provisioning_auth_method == "pkce"
        assert app.provisioning_active
        assert app.provisioning_can_create_accounts
        assert app.provisioning_can_provision_resources

        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_auto",
                "email": "cimd-auto@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_cimd_scope_ceiling_refreshes_on_agentic_auth_after_metadata_edit(self, mock_get, _url_mock):
        from posthog.api.oauth.cimd import _cache_key, register_cimd_provisioning_application_task

        initial = _make_cimd_metadata()
        initial["com.posthog"] = {"scopes": ["insight:read"]}
        mock_get.return_value = _cimd_mock_response(initial)
        register_cimd_provisioning_application_task(CIMD_PROV_URL)

        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        assert app.scopes == ["insight:read"]

        # Partner edits the live metadata to widen the ceiling; the cached doc goes stale.
        real_cache.delete(_cache_key(CIMD_PROV_URL))
        widened = _make_cimd_metadata()
        widened["com.posthog"] = {"scopes": ["insight:read", "dashboard:read"]}
        mock_get.return_value = _cimd_mock_response(widened)

        # A later agentic provisioning auth request must propagate the edit — the bug was that
        # this raw-lookup path never refreshed, so the ceiling stayed frozen at registration.
        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_refresh_e2e",
                "email": "cimd-refresh-e2e@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 200

        app.refresh_from_db()
        assert app.scopes == ["insight:read", "dashboard:read"]

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_existing_cimd_app_gets_provisioning_backfilled(self, mock_refresh, _url_mock):
        OAuthApplication.objects.create(
            name="Pre-existing CIMD",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
        )

        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_backfill",
                "email": "cimd-backfill@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 200

        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        assert app.provisioning_auth_method == "pkce"
        assert app.provisioning_active

    def test_cimd_backfill_db_error_degrades_to_unauthorized(self, _url_mock):
        OAuthApplication.objects.create(
            name="CIMD DB Error App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
        )
        with patch(
            "ee.api.agentic_provisioning.authentication.apply_provisioning_defaults",
            side_effect=RuntimeError("simulated DB error"),
        ):
            _, challenge = self._pkce_pair()
            res = self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": "req_cimd_db_err",
                    "email": "cimd-db-err@example.com",
                    "client_id": CIMD_PROV_URL,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
            )
        assert res.status_code == 401

    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_new_cimd_url_returns_202_not_401(self, mock_task, _url_mock):
        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_fail",
                "email": "cimd-fail@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 202
        assert res.json()["type"] == "registering"
        mock_task.delay.assert_called_once()

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_partner_rate_limit_enforced_after_threshold(self, mock_refresh, _url_mock):
        OAuthApplication.objects.create(
            name="Rate Limit Test CIMD",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
            provisioning_auth_method="pkce",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_rate_limit_account_requests=10,
        )

        _, challenge = self._pkce_pair()

        def post_account_request(email: str):
            return self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": f"req_{email}",
                    "email": email,
                    "client_id": CIMD_PROV_URL,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
            )

        assert post_account_request("ratelimit-1@example.com").status_code == 200

        partner = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        partner.provisioning_rate_limit_account_requests = 2
        partner.save(update_fields=["provisioning_rate_limit_account_requests"])

        assert post_account_request("ratelimit-2@example.com").status_code == 200
        res = post_account_request("ratelimit-3@example.com")
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "rate_limited"

    @patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[])
    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_cimd_domain_rate_limit_blocks_excessive_registrations(self, mock_task, _url_mock):
        from ee.api.agentic_provisioning.views import CIMD_DOMAIN_RATE_LIMIT_MAX

        base_domain = "evil.example.com"
        _, challenge = self._pkce_pair()

        for i in range(CIMD_DOMAIN_RATE_LIMIT_MAX):
            url = f"https://{base_domain}/path-{i}/metadata.json"
            res = self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": f"req_domain_rl_{i}",
                    "email": f"domain-rl-{i}@example.com",
                    "client_id": url,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
            )
            assert res.status_code == 202, f"Request {i} failed: {res.json()}"

        url = f"https://{base_domain}/path-blocked/metadata.json"
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_domain_rl_blocked",
                "email": "domain-rl-blocked@example.com",
                "client_id": url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "rate_limited"

    @patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[])
    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_cimd_domain_rate_limit_does_not_block_different_domains(self, mock_task, _url_mock):
        from ee.api.agentic_provisioning.views import CIMD_DOMAIN_RATE_LIMIT_MAX

        _, challenge = self._pkce_pair()

        for i in range(CIMD_DOMAIN_RATE_LIMIT_MAX + 2):
            url = f"https://domain-{i}.example.com/.well-known/metadata.json"
            res = self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": f"req_diff_domain_{i}",
                    "email": f"diff-domain-{i}@example.com",
                    "client_id": url,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
            )
            assert res.status_code == 202, f"Request {i} for domain-{i} failed: {res.json()}"

    @patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[])
    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_cimd_domain_rate_limit_skipped_for_existing_apps(self, mock_refresh, _url_mock):
        from ee.api.agentic_provisioning.views import CIMD_DOMAIN_RATE_LIMIT_MAX

        base_domain = "existing.example.com"
        _, challenge = self._pkce_pair()

        for i in range(CIMD_DOMAIN_RATE_LIMIT_MAX + 1):
            url = f"https://{base_domain}/path-{i}/metadata.json"
            OAuthApplication.objects.create(
                name=f"Existing CIMD {i}",
                client_secret="",
                client_type=OAuthApplication.CLIENT_PUBLIC,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://127.0.0.1:3000/callback",
                algorithm="RS256",
                is_cimd_client=True,
                cimd_metadata_url=url,
                provisioning_auth_method="pkce",
                provisioning_active=True,
                provisioning_can_create_accounts=True,
                provisioning_can_provision_resources=True,
            )

        url = f"https://{base_domain}/path-0/metadata.json"
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_existing_domain",
                "email": "existing-domain@example.com",
                "client_id": url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 200

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_self_serve_org_named_after_client_name(self, mock_refresh, _url_mock):
        OAuthApplication.objects.create(
            name="Partner App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
            provisioning_auth_method="pkce",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        email = "cimd-org-name@example.com"
        _, challenge = self._pkce_pair()
        self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_org",
                "email": email,
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )

        user = User.objects.get(email=email)
        org = user.organization_memberships.first().organization
        assert org.name == f"Partner App ({email})"

    def test_blocked_cimd_url_returns_unauthorized(self, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url

        block_cimd_url(CIMD_PROV_URL)

        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_blocked",
                "email": "blocked@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 401

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_blocked_cimd_url_with_existing_app_returns_unauthorized(self, mock_refresh, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url

        OAuthApplication.objects.create(
            name="Blocked CIMD App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
            provisioning_auth_method="pkce",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )
        block_cimd_url(CIMD_PROV_URL)

        _, challenge = self._pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_blocked_existing",
                "email": "blocked-existing@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
        )
        assert res.status_code == 401
