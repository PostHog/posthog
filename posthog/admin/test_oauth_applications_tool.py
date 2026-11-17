from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.api.oauth.provisioning_review import append_run_log
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import CIMDProvisioningReview, ProvisioningReviewStatus

TOOL_URL = "/admin/console/tools/oauth-applications/"


class TestOAuthApplicationsTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.app = OAuthApplication.objects.create(
            name="Waiting Partner",
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

    def _staff_app(self, name: str, **fields) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name=name,
            client_id=f"{name.lower().replace(' ', '_')}_client_id",
            client_secret="secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            **fields,
        )

    @parameterized.expand(
        [
            ("everything", "", {"Waiting Partner", "Active Partner", "Blocked Partner", "Plain Client"}),
            ("name", "q=active", {"Active Partner"}),
            ("client_id", "q=app.example.com", {"Waiting Partner"}),
            ("staff_created", "kind=staff", {"Active Partner", "Blocked Partner", "Plain Client"}),
            ("any_partner", "provisioning=partner", {"Waiting Partner", "Active Partner", "Blocked Partner"}),
            ("on", "provisioning=on", {"Active Partner"}),
            ("off", "provisioning=off", {"Waiting Partner"}),
            ("blocked", "provisioning=blocked", {"Blocked Partner"}),
            ("waiting_for_staff", "review=needs_human", {"Waiting Partner"}),
            ("no_review", "review=none", {"Active Partner", "Blocked Partner", "Plain Client"}),
        ]
    )
    def test_the_list_filters_applications(self, _name, query, expected) -> None:
        self._review(ProvisioningReviewStatus.NEEDS_HUMAN)
        self._staff_app(
            "Active Partner",
            is_provisioning_partner=True,
            _provisioning_config=ProvisioningConfig(active=True).model_dump(mode="json"),
        )
        self._staff_app(
            "Blocked Partner",
            is_provisioning_partner=True,
            _provisioning_config=ProvisioningConfig(disabled=True).model_dump(mode="json"),
        )
        self._staff_app("Plain Client")

        content = self.client.get(f"{TOOL_URL}?{query}").content.decode()

        shown = {
            name for name in ("Waiting Partner", "Active Partner", "Blocked Partner", "Plain Client") if name in content
        }
        assert shown == expected
