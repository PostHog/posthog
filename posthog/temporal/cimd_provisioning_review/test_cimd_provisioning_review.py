import uuid
from datetime import timedelta
from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.oauth.provisioning_review import send_partner_review_email, settle_review
from posthog.egress.firecrawl import FirecrawlNotConfigured, FirecrawlScrape, FirecrawlScrapeFailed, FirecrawlSearch
from posthog.email import WORKFLOWS_TEMPLATE_ID_MAP
from posthog.llm.system_one import NoulAnswer, RefusalAnswer, SystemOneResult
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.instance_setting import set_instance_setting
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.temporal.cimd_provisioning_review.activities import _research
from posthog.temporal.cimd_provisioning_review.judgment import (
    THRESHOLDS,
    PartnerJudgment,
    PartnerRegistration,
    outcome_for,
)
from posthog.temporal.cimd_provisioning_review.research import research_domain
from posthog.temporal.cimd_provisioning_review.types import (
    CIMDProvisioningReviewInputs,
    ReviewOutcome,
    SettleReviewInputs,
    StageResult,
)
from posthog.temporal.cimd_provisioning_review.workflow import CIMDProvisioningReviewWorkflow


class TestOutcomeFor(SimpleTestCase):
    @parameterized.expand(
        [
            ("clearly_legitimate", 0.95, 0.01, 0.9, ReviewOutcome.ACCEPT),
            ("clearly_malicious", 0.1, 0.97, 0.9, ReviewOutcome.REJECT),
            # A lookalike of a real brand reads as both, and must not get in.
            ("legitimate_and_malicious", 0.95, 0.97, 0.9, ReviewOutcome.REJECT),
            ("legitimate_on_a_shared_host", 0.95, 0.01, 0.2, ReviewOutcome.NEEDS_HUMAN),
            ("unsure", 0.6, 0.3, 0.9, ReviewOutcome.NEEDS_HUMAN),
            ("legitimate_with_some_doubt", 0.95, 0.2, 0.9, ReviewOutcome.NEEDS_HUMAN),
            ("legitimacy_refused", None, 0.01, 0.9, ReviewOutcome.NEEDS_HUMAN),
            ("abuse_refused", 0.95, None, 0.9, ReviewOutcome.NEEDS_HUMAN),
            ("own_site_refused", 0.95, 0.01, None, ReviewOutcome.NEEDS_HUMAN),
        ]
    )
    def test_thresholds(self, _name, legitimate, malicious, own_site, expected):
        judgment = PartnerJudgment(model="jev", legitimate=legitimate, malicious=malicious, own_site=own_site)

        assert outcome_for(judgment, THRESHOLDS, unsettled=ReviewOutcome.NEEDS_HUMAN) == expected


def _registration(client_uri: str | None) -> PartnerRegistration:
    return PartnerRegistration(
        client_id="https://app.example.com/client.json",
        domain="example.com",
        client_name="Example",
        redirect_uris=(),
        logo_uri=None,
        jwks_uri=None,
        requested_scopes=(),
        optional_scopes=(),
        client_type="public",
        token_endpoint_auth_method="none",
        partner_tier="public",
        attested_by_posthog_organization=None,
        registered_at=None,
        document={"client_uri": client_uri},
        contact_domains=(),
    )


class TestHomepageUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("own_homepage", "https://www.example.com/product", "https://www.example.com/product"),
            # A homepage on another domain would let a fake client borrow a real company's site as evidence.
            ("another_domains_homepage", "https://stripe.com/", "https://example.com/"),
            ("plain_http", "http://example.com/", "https://example.com/"),
            ("no_client_uri", None, "https://example.com/"),
        ]
    )
    def test_research_scrapes_only_the_clients_own_domain(self, _name, client_uri, expected):
        assert _registration(client_uri).homepage_url() == expected


def _search(query: str, **_: object) -> FirecrawlSearch:
    return FirecrawlSearch(query=query, results=())


class TestResearchDomain(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "own_page",
                FirecrawlScrape(url="u", final_url="https://www.example.com/", title="Example", status_code=200),
                True,
                "Example",
                None,
            ),
            (
                "page_not_found",
                FirecrawlScrape(url="u", final_url="https://example.com/", status_code=404),
                False,
                None,
                None,
            ),
            # Another company's site says nothing about this client, so its content never reaches Jev.
            (
                "redirect_elsewhere",
                FirecrawlScrape(url="u", final_url="https://stripe.com/", title="Stripe", status_code=200),
                True,
                None,
                "stripe.com",
            ),
            ("site_failed_to_load", FirecrawlScrapeFailed("unsuccessful"), False, None, None),
            # Firecrawl answers 500 when the target site does not resolve.
            ("site_does_not_exist", FirecrawlScrapeFailed("engines failed", status_code=500), False, None, None),
        ]
    )
    def test_homepage_evidence(self, _name, scraped, reachable, title, redirected_to):
        with (
            patch("posthog.temporal.cimd_provisioning_review.research.scrape", side_effect=[scraped]),
            patch("posthog.temporal.cimd_provisioning_review.research.search", side_effect=_search),
        ):
            homepage = research_domain(
                "example.com", homepage_url="https://example.com/", client_name="Example"
            ).homepage

        assert (homepage.reachable, homepage.title, homepage.redirected_to_domain) == (reachable, title, redirected_to)

    def test_a_firecrawl_rate_limit_is_retried_not_reported_as_a_dead_site(self):
        status_code = 429
        with (
            patch(
                "posthog.temporal.cimd_provisioning_review.research.scrape",
                side_effect=FirecrawlScrapeFailed("busy", status_code=status_code),
            ),
            patch("posthog.temporal.cimd_provisioning_review.research.search", side_effect=_search),
            pytest.raises(FirecrawlScrapeFailed),
        ):
            research_domain("example.com", homepage_url="https://example.com/", client_name="Example")


def _make_app(client_id: str = "https://app.example.com/client.json", **provisioning: bool) -> OAuthApplication:
    return OAuthApplication.objects.create(
        name="Example",
        client_id=client_id,
        is_cimd_client=True,
        client_secret="",
        client_type=OAuthApplication.CLIENT_PUBLIC,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://app.example.com/callback",
        algorithm="RS256",
        is_provisioning_partner=True,
        _provisioning_config=ProvisioningConfig(
            can_create_accounts=True, can_provision_resources=True, **provisioning
        ).model_dump(mode="json"),
    )


class TestSettleReview(APIBaseTest):
    @parameterized.expand(
        [
            ("accepted", ProvisioningReviewStatus.ACCEPTED, False, True, False),
            ("rejected", ProvisioningReviewStatus.REJECTED, False, False, True),
            ("needs_human", ProvisioningReviewStatus.NEEDS_HUMAN, False, False, False),
            # An admin switched the partner off while it waited, and an accept must not undo that.
            ("accepted_after_admin_disabled", ProvisioningReviewStatus.ACCEPTED, True, False, True),
        ]
    )
    @time_machine.travel("2026-11-16T12:00:00Z", tick=False)
    def test_verdict_applies_to_the_partner(self, _name, status, disabled_before, expected_active, expected_disabled):
        app = _make_app(disabled=disabled_before)
        CIMDProvisioningReview.objects.create(application=app, domain="example.com")
        OAuthAccessToken.objects.create(
            application=app, user=self.user, token="pha_review_token", expires=timezone.now() + timedelta(hours=1)
        )

        with (
            patch("posthog.api.oauth.provisioning_review.send_partner_review_email") as send_email,
            self.captureOnCommitCallbacks(execute=True),
        ):
            settled = settle_review(str(app.pk), status=status, stage=ProvisioningReviewStage.RESEARCH, reason="test")

        assert settled is True
        send_email.delay.assert_called_once_with(str(app.provisioning_review.pk), status)
        app.refresh_from_db()
        assert app.provisioning.active is expected_active
        assert app.provisioning.disabled is expected_disabled
        token_survives = status != ProvisioningReviewStatus.REJECTED
        assert OAuthAccessToken.objects.filter(application=app).exists() is token_survives
        assert CIMDProvisioningReview.objects.get(application=app).status == status

    def test_a_decision_staff_made_is_kept(self):
        app = _make_app()
        CIMDProvisioningReview.objects.create(
            application=app, domain="example.com", status=ProvisioningReviewStatus.ACCEPTED
        )

        settled = settle_review(
            str(app.pk),
            status=ProvisioningReviewStatus.REJECTED,
            stage=ProvisioningReviewStage.RESEARCH,
            reason="late run",
        )

        assert settled is False
        app.refresh_from_db()
        assert app.provisioning.disabled is False
        assert CIMDProvisioningReview.objects.get(application=app).status == ProvisioningReviewStatus.ACCEPTED


class TestSendPartnerReviewEmail(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

    def _review(self, status: ProvisioningReviewStatus, *, organization: Organization | None) -> CIMDProvisioningReview:
        app = _make_app()
        app.organization = organization
        app.save(update_fields=["organization"])
        return CIMDProvisioningReview.objects.create(
            application=app,
            domain="example.com",
            status=status,
            decided_at=timezone.now(),
            partner_message="Add a homepage to your metadata document.",
        )

    @parameterized.expand(
        [
            (ProvisioningReviewStatus.ACCEPTED, "oauth_app_provisioning_accepted"),
            (ProvisioningReviewStatus.REJECTED, "oauth_app_provisioning_rejected"),
            (ProvisioningReviewStatus.NEEDS_HUMAN, "oauth_app_provisioning_in_review"),
        ]
    )
    @patch("posthog.api.oauth.provisioning_review.EmailMessage")
    def test_emails_the_admins_of_the_owning_organization(self, status, template_name, MockEmailMessage) -> None:
        sent = mock_email_messages(MockEmailMessage)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        User.objects.create_and_join(self.organization, "member@example.com", None)
        review = self._review(status, organization=self.organization)

        send_partner_review_email(str(review.pk), status)

        assert len(sent) == 1
        assert [recipient["raw_email"] for recipient in sent[0].to] == [self.user.email]
        assert sent[0].template_name == template_name
        assert sent[0].template_name in WORKFLOWS_TEMPLATE_ID_MAP
        assert "Add a homepage to your metadata document." in sent[0].html_body

    @parameterized.expand(
        [
            ("superseded_by_a_later_decision", ProvisioningReviewStatus.REJECTED, True),
            ("app_without_an_organization", ProvisioningReviewStatus.ACCEPTED, False),
        ]
    )
    @patch("posthog.api.oauth.provisioning_review.EmailMessage")
    def test_sends_nothing(self, _name, current_status, has_organization, MockEmailMessage) -> None:
        sent = mock_email_messages(MockEmailMessage)
        review = self._review(current_status, organization=self.organization if has_organization else None)

        send_partner_review_email(str(review.pk), ProvisioningReviewStatus.ACCEPTED)

        assert sent == []


class _FakeSystemOne:
    def __init__(self, legitimate: float | None, malicious: float | None, own_site: float | None = 0.9) -> None:
        self.answers = {
            "legitimate": RefusalAnswer() if legitimate is None else NoulAnswer(probability=legitimate),
            "malicious": RefusalAnswer() if malicious is None else NoulAnswer(probability=malicious),
            "own_site": RefusalAnswer() if own_site is None else NoulAnswer(probability=own_site),
        }
        self.states: list[Any] = []

    def decide(self, *, state, questions) -> SystemOneResult:
        self.states.append(state)
        return SystemOneResult(model="jev-test", answers=self.answers, input_tokens=None)


class TestReviewStages(APIBaseTest):
    def _patch_jev(self, fake: _FakeSystemOne):
        return patch("posthog.temporal.cimd_provisioning_review.judgment.build_system_one_client", return_value=fake)

    @parameterized.expand(
        [
            ("same_host", "example.com", "app.example.com", False, 0.9, True),
            ("same_host_shared_service", "example.com", "app.example.com", False, 0.2, False),
            # A hosting platform missing from the public suffix list gives each user a subdomain of one domain.
            ("another_subdomain", "example.com", "tenant.example.com", False, 0.9, False),
            # Blocking the accepted partner withdraws its vouching for the host.
            ("accepted_partner_disabled", "example.com", "app.example.com", True, 0.9, False),
            # IP hosts have no registrable domain, and one accepted IP client must not vouch for the rest.
            ("no_registrable_domain", "", "app.example.com", False, 0.9, False),
            # PostHog serves customer-controlled documents under its own domain.
            ("posthog_domain", "posthog.com", "app.example.com", False, 0.9, False),
        ]
    )
    def test_research_reuses_an_accepted_host(
        self, _name, domain, second_host, accepted_disabled, own_site, expected_shortcut
    ):
        accepted = _make_app(client_id="https://app.example.com/client.json", active=True, disabled=accepted_disabled)
        CIMDProvisioningReview.objects.create(
            application=accepted, domain=domain, status=ProvisioningReviewStatus.ACCEPTED
        )
        second = _make_app(client_id=f"https://{second_host}/staging-client.json")
        CIMDProvisioningReview.objects.create(
            application=second, domain=domain, research_evidence={"homepage": {"reachable": True}}
        )
        jev = _FakeSystemOne(legitimate=0.5, malicious=0.02, own_site=own_site)

        with self._patch_jev(jev):
            result = _research(str(second.pk))

        expected = ReviewOutcome.ACCEPT if expected_shortcut else ReviewOutcome.NEEDS_HUMAN
        assert result.outcome == expected
        assert (result.stage == ProvisioningReviewStage.HOST_ALREADY_ACCEPTED) is expected_shortcut

    def test_research_retry_judges_the_saved_evidence_without_searching_again(self):
        app = _make_app()
        saved = {"homepage": {"url": "https://example.com/", "reachable": True}}
        CIMDProvisioningReview.objects.create(application=app, domain="example.com", research_evidence=saved)
        jev = _FakeSystemOne(legitimate=0.95, malicious=0.01)

        with (
            self._patch_jev(jev),
            patch(
                "posthog.temporal.cimd_provisioning_review.research.scrape",
                side_effect=FirecrawlNotConfigured("must not be called"),
            ),
        ):
            result = _research(str(app.pk))

        assert result.outcome == ReviewOutcome.ACCEPT
        assert jev.states[0]["evidence"] == saved
        assert jev.states[0]["client"]["domain"] == "example.com"
        review = CIMDProvisioningReview.objects.get(application=app)
        assert review.research_judgment == {
            "model": "jev-test",
            "legitimate": 0.95,
            "malicious": 0.01,
            "own_site": 0.9,
        }

    def test_research_without_firecrawl_hands_the_review_to_staff(self):
        app = _make_app()
        CIMDProvisioningReview.objects.create(application=app, domain="example.com")

        with (
            patch(
                "posthog.temporal.cimd_provisioning_review.research.scrape",
                side_effect=FirecrawlNotConfigured("no key"),
            ),
            pytest.raises(ApplicationError) as raised,
        ):
            _research(str(app.pk))

        assert raised.value.non_retryable is True


@pytest.mark.asyncio
async def test_workflow_hands_the_review_to_staff_when_research_keeps_failing():
    settled: list[SettleReviewInputs] = []

    @activity.defn(name="cimd-provisioning-review-research")
    async def research(inputs: CIMDProvisioningReviewInputs) -> StageResult:
        raise ApplicationError("Firecrawl is down", non_retryable=True)

    @activity.defn(name="cimd-provisioning-review-settle")
    async def settle(inputs: SettleReviewInputs) -> bool:
        settled.append(inputs)
        return True

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CIMDProvisioningReviewWorkflow],
            activities=[research, settle],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            outcome = await env.client.execute_workflow(
                CIMDProvisioningReviewWorkflow.run,
                CIMDProvisioningReviewInputs(application_id="app-1"),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=5),
            )

    assert outcome == ReviewOutcome.NEEDS_HUMAN
    assert [(s.outcome, s.stage) for s in settled] == [
        (ReviewOutcome.NEEDS_HUMAN, ProvisioningReviewStage.PIPELINE_FAILED)
    ]
