from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication, OAuthRefreshToken
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)

JWKS_URI = "https://app.example.com/.well-known/jwks.json"


class TestOAuthApplicationConsole(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _app(
        self,
        *,
        is_partner: bool = True,
        config: ProvisioningConfig | None = None,
        client_type: str = OAuthApplication.CLIENT_PUBLIC,
        jwks_uri: str | None = None,
    ) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name="Example",
            client_id="https://app.example.com/client.json",
            is_cimd_client=True,
            client_secret="",
            client_type=client_type,
            jwks_uri=jwks_uri,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://app.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=is_partner,
            _provisioning_config=(config or ProvisioningConfig(can_provision_resources=True)).model_dump(mode="json"),
        )

    def _post(self, app: OAuthApplication, operation: str, data: dict):
        return self.client.post(f"/admin/console/oauth-applications/{app.pk}/{operation}/", data)

    @parameterized.expand(
        [
            ("accept_needs_human", ProvisioningReviewStatus.NEEDS_HUMAN, "accept", "Accepted: Staff: Checked the site"),
            ("block_needs_human", ProvisioningReviewStatus.NEEDS_HUMAN, "block", "Rejected: Staff: Checked the site"),
            ("accept_pending", ProvisioningReviewStatus.PENDING, "accept", "Accepted: Staff: Checked the site"),
            (
                "block_accepted",
                ProvisioningReviewStatus.ACCEPTED,
                "block",
                "Changed from Accepted to Rejected: Staff: Checked the site",
            ),
            (
                "accept_rejected",
                ProvisioningReviewStatus.REJECTED,
                "accept",
                "Changed from Rejected to Accepted: Staff: Checked the site",
            ),
            ("accept_without_review", None, "accept", None),
            ("block_without_review", None, "block", None),
        ]
    )
    def test_staff_accept_or_block_a_partner(self, _name, review_status, operation, expected_log) -> None:
        app = self._app(
            config=ProvisioningConfig(
                active=review_status == ProvisioningReviewStatus.ACCEPTED,
                disabled=review_status == ProvisioningReviewStatus.REJECTED,
            )
        )
        review = (
            CIMDProvisioningReview.objects.create(application=app, domain="example.com", status=review_status)
            if review_status is not None
            else None
        )

        response = self._post(
            app, f"provisioning/{operation}", {"reason": "Checked the site", "partner_message": "Thanks for waiting."}
        )

        assert response.status_code == 302, response.content
        accepted = operation == "accept"
        app.refresh_from_db()
        assert app.provisioning.active is accepted
        assert app.provisioning.disabled is not accepted
        if review is not None:
            review.refresh_from_db()
            assert review.status == (
                ProvisioningReviewStatus.ACCEPTED if accepted else ProvisioningReviewStatus.REJECTED
            )
            assert review.decided_stage == ProvisioningReviewStage.STAFF
            assert review.run_log[-1]["message"] == expected_log
            assert review.partner_message == "Thanks for waiting."

    def test_block_reaches_a_partner_left_active_and_disabled(self) -> None:
        app = self._app(config=ProvisioningConfig(active=True, disabled=True))

        page = self.client.get(f"/admin/console/oauth-applications/{app.pk}/").content.decode()
        response = self._post(app, "provisioning/block", {"reason": "Finish the old block"})

        assert "On, though marked blocked" in page
        assert response.status_code == 302, response.content
        app.refresh_from_db()
        assert (app.provisioning.active, app.provisioning.disabled) == (False, True)

    @parameterized.expand([("active", True, False, "accept"), ("blocked", False, True, "block")])
    def test_the_current_decision_is_not_offered_again(self, _name, active, disabled, operation) -> None:
        app = self._app(config=ProvisioningConfig(active=active, disabled=disabled))

        response = self._post(app, f"provisioning/{operation}", {"reason": "Second thoughts"})

        assert response.status_code == 404
        app.refresh_from_db()
        assert (app.provisioning.active, app.provisioning.disabled) == (active, disabled)

    @parameterized.expand(
        [
            ("grant_to_a_signing_partner", OAuthApplication.CLIENT_CONFIDENTIAL, JWKS_URI, False),
            ("public_partner_creates_accounts", OAuthApplication.CLIENT_PUBLIC, None, True),
            ("client_secret_partner_creates_accounts", OAuthApplication.CLIENT_CONFIDENTIAL, None, True),
        ]
    )
    def test_change_capabilities(self, _name, client_type, jwks_uri, expects_refusal) -> None:
        app = self._app(is_partner=False, client_type=client_type, jwks_uri=jwks_uri)

        response = self._post(
            app,
            "provisioning/capabilities",
            {"is_provisioning_partner": "on", "can_create_accounts": "on", "reason": "Signed partner agreement"},
        )

        app.refresh_from_db()
        if expects_refusal:
            assert response.status_code == 400
            assert app.is_provisioning_partner is False
            assert app.provisioning.can_create_accounts is False
        else:
            assert response.status_code == 302, response.content
            assert app.is_provisioning_partner is True
            assert app.provisioning.can_create_accounts is True
            # An unticked box turns a capability off rather than leaving it as it was.
            assert app.provisioning.can_provision_resources is False

    def test_removing_a_partner_turns_provisioning_off(self) -> None:
        app = self._app(config=ProvisioningConfig(active=True))
        refresh_token = OAuthRefreshToken.objects.create(application=app, user=self.user, token="partner_refresh")

        response = self._post(app, "provisioning/capabilities", {"reason": "No longer a partner"})

        assert response.status_code == 302, response.content
        app.refresh_from_db()
        refresh_token.refresh_from_db()
        assert app.is_provisioning_partner is False
        assert app.provisioning.active is False
        assert refresh_token.revoked is not None

    def test_a_partner_that_already_cannot_sign_stays_editable(self) -> None:
        app = self._app(config=ProvisioningConfig(can_create_accounts=True))

        response = self._post(
            app,
            "provisioning/capabilities",
            {"is_provisioning_partner": "on", "can_create_accounts": "on", "reason": "Lower its other settings"},
        )

        assert response.status_code == 302, response.content

    @parameterized.expand(
        [
            ("override", {"account_requests": 100}, "250", {"account_requests": 250}),
            ("unlimited", {}, "-1", {"account_requests": -1}),
            ("blank_clears", {"account_requests": 100}, "", {}),
            ("zero_is_refused", {"account_requests": 100}, "0", {"account_requests": 100}),
        ]
    )
    def test_change_rate_limits(self, _name, stored, submitted, expected) -> None:
        app = self._app(config=ProvisioningConfig(rate_limits=stored))

        self._post(app, "provisioning/rate-limits", {"account_requests": submitted, "reason": "Launch traffic"})

        app.refresh_from_db()
        assert app.provisioning.rate_limits == expected

    def test_sign_out_every_connection(self) -> None:
        app = self._app()

        response = self._post(app, "overview/sign-out", {"reason": "Leaked refresh token"})

        assert response.status_code == 302, response.content
        app.refresh_from_db()
        assert app.sessions_revoked_at is not None
