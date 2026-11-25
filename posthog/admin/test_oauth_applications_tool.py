from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.admin.console.oauth_application_panels import DECISION_OPERATION_KEYS
from posthog.api.oauth.provisioning_review import append_run_log
from posthog.models.instance_setting import override_instance_config
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import CIMDProvisioningReview, ProvisioningReviewStatus

TOOL_URL = "/admin/console/tools/oauth-applications/"
ALL_APPS = ("Waiting Partner", "Active Partner", "Blocked Partner", "Plain Client", "Bare Partner")


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

    @parameterized.expand(
        [
            (
                "waiting_for_staff",
                ProvisioningReviewStatus.NEEDS_HUMAN,
                {},
                ["accept", "request-changes", "decline", "block"],
                True,
            ),
            (
                "accepted",
                ProvisioningReviewStatus.ACCEPTED,
                {"active": True},
                ["request-changes", "decline", "block"],
                False,
            ),
            ("declined", ProvisioningReviewStatus.DECLINED, {}, ["accept", "request-changes", "block"], False),
            (
                "changes_requested",
                ProvisioningReviewStatus.CHANGES_REQUESTED,
                {},
                ["accept", "decline", "block"],
                False,
            ),
            (
                "blocked",
                ProvisioningReviewStatus.REJECTED,
                {"disabled": True},
                ["accept", "decline"],
                False,
            ),
        ]
    )
    def test_both_pages_offer_the_decisions_after_the_timeline(self, _name, status, config, offered, waiting) -> None:
        self.app._provisioning_config = ProvisioningConfig(**config).model_dump(mode="json")
        self.app.save()
        review = self._review(status)

        content = self.client.get(f"{TOOL_URL}?review={review.pk}").content.decode()

        for key in DECISION_OPERATION_KEYS:
            url = f"/admin/console/oauth-applications/{self.app.pk}/provisioning/{key}/"
            assert (url in content) == (key in offered)
            if key in offered:
                assert content.index("Timeline") < content.index(url)
        assert ("is waiting for a staff decision" in content) == waiting
        app_page = self.client.get(f"/admin/console/oauth-applications/{self.app.pk}/").content.decode()
        assert (
            "Read the review, then accept, ask for changes, decline or block the partner below." in app_page
        ) == waiting

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
            ("everything", "", set(ALL_APPS)),
            ("name", "q=active", {"Active Partner"}),
            ("client_id", "q=app.example.com", {"Waiting Partner"}),
            ("staff_created", "kind=staff", {"Active Partner", "Blocked Partner", "Plain Client", "Bare Partner"}),
            (
                "any_partner",
                "provisioning=partner",
                {"Waiting Partner", "Active Partner", "Blocked Partner", "Bare Partner"},
            ),
            ("on", "provisioning=on", {"Active Partner"}),
            ("off", "provisioning=off", {"Waiting Partner", "Bare Partner"}),
            ("blocked", "provisioning=blocked", {"Blocked Partner"}),
            ("waiting_for_staff", "review=needs_human", {"Waiting Partner"}),
            ("no_review", "review=none", {"Active Partner", "Blocked Partner", "Plain Client", "Bare Partner"}),
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
        # Written before the flags existed, so its config has no key for either.
        self._staff_app("Bare Partner", is_provisioning_partner=True, _provisioning_config={})

        content = self.client.get(f"{TOOL_URL}?{query}").content.decode()

        shown = {name for name in ALL_APPS if name in content}
        assert shown == expected

    @parameterized.expand(
        [
            ("linked_through_the_issuer", "https://us.posthog.com", "provisioning=on"),
            ("not_linked", "", "provisioning=off"),
        ]
    )
    def test_requiring_a_link_holds_back_only_unlinked_partners(self, _name, link_issuer, query) -> None:
        self.app._provisioning_config = ProvisioningConfig(active=True).model_dump(mode="json")
        self.app.organization_link_issuer = link_issuer
        self.app.save()

        with override_instance_config("CIMD_PROVISIONING_REQUIRES_ORGANIZATION", True):
            content = self.client.get(f"{TOOL_URL}?{query}").content.decode()

        assert "Waiting Partner" in content

    @parameterized.expand(
        [
            ("waiting_for_a_link", False, "Off until it links a PostHog organization"),
            ("blocked", True, "Blocked"),
        ]
    )
    def test_an_unlinked_partner_reads_as_blocked_when_it_is(self, _name, disabled, label) -> None:
        self.app._provisioning_config = ProvisioningConfig(active=True, disabled=disabled).model_dump(mode="json")
        self.app.save()

        with override_instance_config("CIMD_PROVISIONING_REQUIRES_ORGANIZATION", True):
            content = self.client.get(f"/admin/console/oauth-applications/{self.app.pk}/").content.decode()

        assert label in content
        assert ("Off until it links a PostHog organization" in content) == (not disabled)
