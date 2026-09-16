"""Literals shared by the corpus, fixtures, seeders, and scorers."""

from __future__ import annotations

from typing import Literal

EvalOutcome = Literal["answerable", "needs_clarification", "escalate"]
BlockerType = Literal["none", "customer_info", "knowledge", "contradiction"]
TicketType = Literal["how_to", "diagnostic", "account_billing", "bug", "unactionable"]

SOURCE_SDK_INSTALL = "JavaScript SDK install"
SOURCE_BILLING_INVOICES = "Invoices and billing"
SOURCE_REPLAY_BLANK = "Blank session recordings"
SOURCE_RECORDING_RETENTION = "Session recording retention"
SOURCE_TEAM_POLICY = "Support reply policy"

EVAL_OUTCOMES: tuple[EvalOutcome, ...] = ("answerable", "needs_clarification", "escalate")
BLOCKER_TYPES: tuple[BlockerType, ...] = ("none", "customer_info", "knowledge", "contradiction")
TICKET_TYPES: tuple[TicketType, ...] = ("how_to", "diagnostic", "account_billing", "bug", "unactionable")

# Pipeline `ai_triage.result` values the loop can emit, mapped to the eval outcome
# the fixture asks for.
PIPELINE_RESULT_TO_EVAL_OUTCOME: dict[str, EvalOutcome] = {
    "persisted": "answerable",
    "suggested": "escalate",
    "escalated_with_best": "escalate",
    "escalated_no_reply": "escalate",
    "escalated_with_findings": "escalate",
    "escalated_budget_exhausted": "escalate",
    "skipped_unactionable": "escalate",
    "blocked_unsafe": "escalate",
    "blocked_unsafe_reply": "escalate",
}

# Persist-reply posts a clarifying question and sets this status. Map it here so
# fixtures that expect needs_clarification score correctly once that branch exists.
CLARIFICATION_TRIAGE_STATUS = "awaiting_clarification"

LIVE_EVAL_ENV_VAR = "SUPPORT_REPLY_EVAL_LIVE"
