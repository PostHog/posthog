"""Invented support tickets for the reply-pipeline eval.

Each fixture is a customer message plus the outcome the pipeline should reach, the
BK sources a grounded answer may cite, and the canned draft/validate the mocked
runner injects. Live runs ignore the canned draft and hit the real sandbox.
"""

from __future__ import annotations

from typing import Any

from posthog.dataclasses import frozen

from products.conversations.evals.constants import (
    SOURCE_BILLING_INVOICES,
    SOURCE_RECORDING_RETENTION,
    SOURCE_REPLAY_BLANK,
    SOURCE_SDK_INSTALL,
    BlockerType,
    EvalOutcome,
    TicketType,
)


@frozen
class MockedDraft:
    reply: str
    citation_sources: tuple[str, ...]
    confidence: float
    excerpts: tuple[tuple[str, str], ...] = ()


@frozen
class MockedValidate:
    grounded: bool
    coverage: float
    confidence: float
    missing: tuple[str, ...] = ()


@frozen
class SupportReplyFixture:
    name: str
    prompt: str
    ticket_type: TicketType
    expected_outcome: EvalOutcome
    blocker: BlockerType
    seed_queries: tuple[str, ...]
    expected_citation_sources: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    needs_diagnostics: bool = False
    mocked_draft: MockedDraft | None = None
    mocked_validate: MockedValidate | None = None


def expected_for(fixture: SupportReplyFixture) -> dict[str, Any]:
    """Scorer `expected` payload, keyed by each scorer's `_name()`."""
    payload: dict[str, Any] = {
        "outcome_match": {"outcome": fixture.expected_outcome},
        "citation_precision": {"source_names": list(fixture.expected_citation_sources)},
        "forbidden_claims": {"phrases": list(fixture.forbidden_claims)},
        "cost": {},
    }
    if fixture.expected_outcome == "answerable":
        payload["grounding"] = {"required": True}
    if fixture.expected_outcome == "needs_clarification":
        payload["clarifying_question"] = {"required": True}
    return payload


_ANSWERABLE_VALIDATE = MockedValidate(grounded=True, coverage=0.9, confidence=0.9)
_LOW_VALIDATE = MockedValidate(
    grounded=False,
    coverage=0.2,
    confidence=0.2,
    missing=("customer did not specify the missing fact",),
)


FIXTURES: tuple[SupportReplyFixture, ...] = (
    SupportReplyFixture(
        name="how_to_sdk_install",
        prompt=(
            "Hi, we just signed up for Acme Capture. How do I install the JavaScript SDK "
            "on app.example.com so pageviews start showing up?"
        ),
        ticket_type="how_to",
        expected_outcome="answerable",
        blocker="none",
        seed_queries=("install javascript SDK", "acmeCapture.init"),
        expected_citation_sources=(SOURCE_SDK_INSTALL,),
        forbidden_claims=("refund",),
        mocked_draft=MockedDraft(
            reply=(
                "Add the Acme Capture snippet to the <head> of every page on app.example.com, "
                "with apiHost https://api.example.com and your project token from Project settings. "
                "A reload should send a $pageview."
            ),
            citation_sources=(SOURCE_SDK_INSTALL,),
            confidence=0.9,
            excerpts=((SOURCE_SDK_INSTALL, "acmeCapture.init({ apiHost: 'https://api.example.com'"),),
        ),
        mocked_validate=_ANSWERABLE_VALIDATE,
    ),
    SupportReplyFixture(
        name="diagnostic_blank_replay",
        prompt=(
            "Session replay for checkout on app.example.com/checkout opens as a blank white "
            "canvas. The session still appears in the list. What should we check?"
        ),
        ticket_type="diagnostic",
        expected_outcome="answerable",
        blocker="none",
        needs_diagnostics=True,
        seed_queries=("blank session recording", "blank canvas replay"),
        expected_citation_sources=(SOURCE_REPLAY_BLANK,),
        mocked_draft=MockedDraft(
            reply=(
                "A listed recording that opens blank usually means no DOM snapshots were stored. "
                "Confirm the recorder snippet is on that page, Replay is enabled, the URL is not "
                "blocklisted, and an ad blocker is not stripping the recorder domain."
            ),
            citation_sources=(SOURCE_REPLAY_BLANK,),
            confidence=0.85,
            excerpts=((SOURCE_REPLAY_BLANK, "blank canvas usually means the recorder never captured"),),
        ),
        mocked_validate=_ANSWERABLE_VALIDATE,
    ),
    SupportReplyFixture(
        name="account_billing_invoices",
        prompt="Where do I download last month's invoice PDF for our organization?",
        ticket_type="account_billing",
        expected_outcome="answerable",
        blocker="none",
        seed_queries=("download invoice PDF", "billing invoices"),
        expected_citation_sources=(SOURCE_BILLING_INVOICES,),
        forbidden_claims=("I'll refund", "full refund", "I'll issue a credit"),
        mocked_draft=MockedDraft(
            reply=(
                "Open Organization settings > Billing > Invoices on app.example.com. Each month "
                "is a PDF. Changing the billing email does not resend old invoices."
            ),
            citation_sources=(SOURCE_BILLING_INVOICES,),
            confidence=0.9,
            excerpts=((SOURCE_BILLING_INVOICES, "Organization settings > Billing > Invoices"),),
        ),
        mocked_validate=_ANSWERABLE_VALIDATE,
    ),
    SupportReplyFixture(
        name="how_to_events_missing_sdk",
        prompt="Events aren't showing up in Acme Capture. Can you fix it?",
        ticket_type="how_to",
        expected_outcome="needs_clarification",
        blocker="customer_info",
        seed_queries=("events not showing", "events missing"),
        mocked_draft=MockedDraft(
            reply="Which SDK are you using?",
            citation_sources=(),
            confidence=0.2,
        ),
        mocked_validate=_LOW_VALIDATE,
    ),
    SupportReplyFixture(
        name="diagnostic_its_broken",
        prompt="It's broken.",
        ticket_type="diagnostic",
        expected_outcome="needs_clarification",
        blocker="customer_info",
        needs_diagnostics=True,
        seed_queries=("broken",),
        mocked_draft=MockedDraft(
            reply="Which product surface is broken?",
            citation_sources=(),
            confidence=0.1,
        ),
        mocked_validate=_LOW_VALIDATE,
    ),
    SupportReplyFixture(
        name="account_billing_why_charged",
        prompt="Why was I charged?",
        ticket_type="account_billing",
        expected_outcome="needs_clarification",
        blocker="customer_info",
        seed_queries=("unexpected charge", "invoice"),
        forbidden_claims=("I'll refund", "I'll issue a credit"),
        mocked_draft=MockedDraft(
            reply="Which organization is this for?",
            citation_sources=(),
            confidence=0.2,
        ),
        mocked_validate=_LOW_VALIDATE,
    ),
    SupportReplyFixture(
        name="how_to_holographic_widget",
        prompt=(
            "How do I enable the holographic dashboard widget on app.example.com? I cannot find it in Project settings."
        ),
        ticket_type="how_to",
        expected_outcome="escalate",
        blocker="knowledge",
        seed_queries=("holographic dashboard widget",),
        mocked_draft=MockedDraft(
            reply="I cannot find the holographic dashboard widget in the knowledge base.",
            citation_sources=(),
            confidence=0.0,
        ),
        mocked_validate=MockedValidate(
            grounded=False,
            coverage=0.0,
            confidence=0.0,
            missing=("no documentation for holographic dashboard widget",),
        ),
    ),
    SupportReplyFixture(
        name="diagnostic_retention_contradiction",
        prompt=(
            "Docs say recordings last 30 days but ours vanish after 3 days. Session id "
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee on project proj_eval_001."
        ),
        ticket_type="diagnostic",
        expected_outcome="escalate",
        blocker="contradiction",
        needs_diagnostics=True,
        seed_queries=("session recording retention 30 days", "recordings deleted after 3 days"),
        expected_citation_sources=(SOURCE_RECORDING_RETENTION,),
        mocked_draft=MockedDraft(
            reply=(
                "Paid plans retain recordings for 30 days, so a deletion after 3 days is not "
                "the documented policy. This needs engineering. I have the session id you sent."
            ),
            citation_sources=(SOURCE_RECORDING_RETENTION,),
            confidence=0.4,
            excerpts=((SOURCE_RECORDING_RETENTION, "retains session recordings for 30 days"),),
        ),
        mocked_validate=MockedValidate(
            grounded=True,
            coverage=0.5,
            confidence=0.4,
            missing=("why this project deleted at 3 days",),
        ),
    ),
    SupportReplyFixture(
        name="bug_save_button_404",
        prompt=(
            "The Save button on insight abc123 on app.example.com/insights/abc123 returns HTTP "
            "404 since Tuesday. This used to work. Please fix the product."
        ),
        ticket_type="bug",
        expected_outcome="escalate",
        blocker="none",
        seed_queries=("insight save 404",),
        mocked_draft=MockedDraft(
            reply=(
                "This reads as a product defect, not a usage question. Please send the exact "
                "steps, when it started, and a screenshot of the 404. Engineering will take it from there."
            ),
            citation_sources=(),
            confidence=0.8,
        ),
        mocked_validate=MockedValidate(grounded=True, coverage=0.7, confidence=0.7),
    ),
    SupportReplyFixture(
        name="unactionable_thanks",
        prompt="Thanks, you're the best!",
        ticket_type="unactionable",
        expected_outcome="escalate",
        blocker="none",
        seed_queries=(),
    ),
)

FIXTURES_BY_NAME: dict[str, SupportReplyFixture] = {fixture.name: fixture for fixture in FIXTURES}
