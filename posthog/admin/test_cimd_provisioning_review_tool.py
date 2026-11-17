from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.api.oauth.provisioning_review import append_run_log
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)

TOOL_URL = "/admin/console/tools/cimd-provisioning-reviews/"


class TestCIMDProvisioningReviewTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.app = OAuthApplication.objects.create(
            name="Example",
            client_id="https://app.example.com/client.json",
            is_cimd_client=True,
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://app.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
            _provisioning_config=ProvisioningConfig(can_create_accounts=True, can_provision_resources=True).model_dump(
                mode="json"
            ),
        )

    def _review(self, status: ProvisioningReviewStatus) -> CIMDProvisioningReview:
        return CIMDProvisioningReview.objects.create(application=self.app, domain="example.com", status=status)

    @parameterized.expand(
        [
            ("accept_needs_human", ProvisioningReviewStatus.NEEDS_HUMAN, "accept", True, False),
            ("reject_needs_human", ProvisioningReviewStatus.NEEDS_HUMAN, "reject", False, True),
            ("accept_pending", ProvisioningReviewStatus.PENDING, "accept", True, False),
        ]
    )
    def test_staff_settle_a_review(self, _name, status, operation, expected_active, expected_disabled) -> None:
        review = self._review(status)

        response = self.client.post(f"{TOOL_URL}{operation}/?review={review.pk}", {"reason": "Checked the site"})

        assert response.status_code == 302, response.content
        self.app.refresh_from_db()
        assert self.app.provisioning.active is expected_active
        assert self.app.provisioning.disabled is expected_disabled
        review.refresh_from_db()
        assert review.decided_stage == ProvisioningReviewStage.STAFF
        assert review.reason == "Staff: Checked the site"

    @parameterized.expand(
        [("accepted", ProvisioningReviewStatus.ACCEPTED), ("rejected", ProvisioningReviewStatus.REJECTED)]
    )
    def test_a_settled_review_offers_no_decision(self, _name, status) -> None:
        review = self._review(status)

        response = self.client.post(f"{TOOL_URL}reject/?review={review.pk}", {"reason": "Second thoughts"})

        assert response.status_code == 404
        review.refresh_from_db()
        assert review.status == status

    def test_the_review_page_shows_what_the_run_did(self) -> None:
        review = self._review(ProvisioningReviewStatus.PENDING)
        review.research_judgment = {"model": "jev-test", "legitimate": 0.61, "malicious": 0.02}
        review.save()
        append_run_log(str(self.app.pk), "research", "Jev: legitimate 0.61, malicious 0.02. Next: needs_human")

        content = self.client.get(f"{TOOL_URL}?review={review.pk}").content.decode()

        assert "Jev: legitimate 0.61, malicious 0.02. Next: needs_human" in content
        assert "jev-test" in content
        assert f"cimd-provisioning-review-{self.app.pk}" in content
