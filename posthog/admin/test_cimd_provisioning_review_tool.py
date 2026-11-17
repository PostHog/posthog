from posthog.test.base import BaseTest

from posthog.api.oauth.provisioning_review import append_run_log
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import CIMDProvisioningReview, ProvisioningReviewStatus

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

    def test_the_review_page_shows_what_the_run_did(self) -> None:
        review = self._review(ProvisioningReviewStatus.PENDING)
        review.research_judgment = {"model": "jev-test", "legitimate": 0.61, "malicious": 0.02}
        review.save()
        append_run_log(str(self.app.pk), "research", "Jev: legitimate 0.61, malicious 0.02. Next: needs_human")

        content = self.client.get(f"{TOOL_URL}?review={review.pk}").content.decode()

        assert "Jev: legitimate 0.61, malicious 0.02. Next: needs_human" in content
        assert "jev-test" in content
        assert f"cimd-provisioning-review-{self.app.pk}" in content
        assert f"/admin/console/oauth-applications/{self.app.pk}/" in content
