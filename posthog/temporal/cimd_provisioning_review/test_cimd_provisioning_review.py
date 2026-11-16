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

from posthog.api.oauth.provisioning_review import settle_review
from posthog.egress.firecrawl import FirecrawlNotConfigured
from posthog.llm.system_one import NoulAnswer, RefusalAnswer, SystemOneResult
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.temporal.cimd_provisioning_review.activities import _research, _screen
from posthog.temporal.cimd_provisioning_review.judgment import (
    SCREEN_THRESHOLDS,
    PartnerJudgment,
    PartnerRegistration,
    outcome_for,
)
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
            ("clearly_legitimate", 0.95, 0.01, ReviewOutcome.ACCEPT),
            ("clearly_malicious", 0.1, 0.97, ReviewOutcome.REJECT),
            # A lookalike of a real brand reads as both, and must not get in.
            ("legitimate_and_malicious", 0.95, 0.97, ReviewOutcome.REJECT),
            ("unsure", 0.6, 0.3, ReviewOutcome.RESEARCH),
            ("legitimate_with_some_doubt", 0.95, 0.2, ReviewOutcome.RESEARCH),
            ("legitimacy_refused", None, 0.01, ReviewOutcome.RESEARCH),
            ("abuse_refused", 0.95, None, ReviewOutcome.RESEARCH),
        ]
    )
    def test_thresholds(self, _name, legitimate, malicious, expected):
        judgment = PartnerJudgment(model="jev", legitimate=legitimate, malicious=malicious)

        assert outcome_for(judgment, SCREEN_THRESHOLDS, unsettled=ReviewOutcome.RESEARCH) == expected


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

        settled = settle_review(str(app.pk), status=status, stage=ProvisioningReviewStage.SCREEN, reason="test")

        assert settled is True
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


class _FakeSystemOne:
    def __init__(self, legitimate: float | None, malicious: float | None) -> None:
        self.answers = {
            "legitimate": RefusalAnswer() if legitimate is None else NoulAnswer(probability=legitimate),
            "malicious": RefusalAnswer() if malicious is None else NoulAnswer(probability=malicious),
        }
        self.states: list[Any] = []

    def decide(self, *, state, questions) -> SystemOneResult:
        self.states.append(state)
        return SystemOneResult(model="jev-test", answers=self.answers, input_tokens=None)


class TestReviewStages(APIBaseTest):
    def _patch_jev(self, fake: _FakeSystemOne):
        return patch("posthog.temporal.cimd_provisioning_review.judgment.build_system_one_client", return_value=fake)

    def test_screen_accepts_a_second_client_on_an_accepted_domain_without_asking_jev(self):
        accepted = _make_app(client_id="https://app.example.com/client.json", active=True)
        CIMDProvisioningReview.objects.create(
            application=accepted, domain="example.com", status=ProvisioningReviewStatus.ACCEPTED
        )
        second = _make_app(client_id="https://staging.example.com/client.json")
        CIMDProvisioningReview.objects.create(application=second, domain="example.com")
        jev = _FakeSystemOne(legitimate=0.0, malicious=1.0)

        with self._patch_jev(jev):
            result = _screen(str(second.pk))

        assert result.outcome == ReviewOutcome.ACCEPT
        assert result.stage == ProvisioningReviewStage.DOMAIN_ALREADY_ACCEPTED
        assert jev.states == []

    def test_screen_sends_unsure_registrations_to_research_and_keeps_the_judgment(self):
        app = _make_app()
        CIMDProvisioningReview.objects.create(application=app, domain="example.com")
        jev = _FakeSystemOne(legitimate=0.6, malicious=None)

        with self._patch_jev(jev):
            result = _screen(str(app.pk))

        assert result.outcome == ReviewOutcome.RESEARCH
        assert jev.states[0]["client"]["domain"] == "example.com"
        review = CIMDProvisioningReview.objects.get(application=app)
        assert review.screen_judgment == {"model": "jev-test", "legitimate": 0.6, "malicious": None}

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

    @activity.defn(name="cimd-provisioning-review-screen")
    async def screen(inputs: CIMDProvisioningReviewInputs) -> StageResult:
        return StageResult(outcome=ReviewOutcome.RESEARCH, stage=ProvisioningReviewStage.SCREEN, reason="unsure")

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
            activities=[screen, research, settle],
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
