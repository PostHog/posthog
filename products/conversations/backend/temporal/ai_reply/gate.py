from __future__ import annotations

from typing import Literal

from products.conversations.backend.temporal.ai_reply.constants import (
    AUTO_SEND_MIN_COVERAGE,
    AUTO_SEND_THRESHOLD,
    DRAFT_SELF_CONFIDENCE_FLOOR,
    MAX_CLARIFYING_QUESTIONS,
    SUGGEST_THRESHOLD,
)

ReplyAction = Literal["auto_send", "retry", "clarify", "suggest", "findings"]

FINDINGS_WITHHELD_REASON = "Investigation notes withheld because they contained sensitive data."

_FINDINGS_BLOCKERS = frozenset({"contradiction", "customer_info", "knowledge"})
_FINDINGS_VERDICTS = frozenset({"out_of_scope", "blocked_on_customer", "blocked_on_knowledge"})


def decide_reply_action(
    *,
    grounded: bool,
    coverage: float,
    validator_confidence: float,
    draft_confidence: float,
    blocker: str,
    verdict: str,
    attempt: int,
    max_attempts: int,
) -> ReplyAction:
    # Either judge alone can be overconfident, so a public reply needs both plus coverage.
    if (
        grounded
        and coverage >= AUTO_SEND_MIN_COVERAGE
        and validator_confidence >= AUTO_SEND_THRESHOLD
        and draft_confidence >= DRAFT_SELF_CONFIDENCE_FLOOR
        and blocker == "none"
        and verdict == "answerable"
    ):
        return "auto_send"
    if blocker == "customer_info" or verdict == "blocked_on_customer":
        return "clarify"
    if blocker == "contradiction" or verdict == "out_of_scope":
        return "findings"
    # Retry only on a validator knowledge gap. The draft verdict is not a retry signal.
    if blocker == "knowledge":
        if attempt < max_attempts - 1:
            return "retry"
        return "findings"
    # The agent said it could not answer. Do not present that draft as a proposed reply.
    if verdict == "blocked_on_knowledge":
        return "findings"
    if blocker == "none" and verdict == "answerable" and grounded and validator_confidence >= SUGGEST_THRESHOLD:
        return "suggest"
    return "findings"


def findings_reason_for(*, blocker: str, verdict: str, grounded: bool) -> str:
    if blocker == "contradiction":
        return "This answer contradicts the cited sources, so it was not sent."
    if verdict == "out_of_scope":
        return "This ticket is outside what support can answer."
    if blocker == "customer_info" or verdict == "blocked_on_customer":
        return "Need more information from the customer."
    if blocker == "knowledge" or verdict == "blocked_on_knowledge":
        return "The knowledge base and docs did not cover this."
    if not grounded:
        return "This draft does not match the sources, so it was not sent."
    return "This draft was not confident enough to propose as a reply."


def should_persist_findings(
    *,
    investigation_summary: str,
    unknowns: list[str],
    clarifying_questions: list[str],
    citations: list[str],
    blocker: str,
    verdict: str,
) -> bool:
    if investigation_summary.strip() or unknowns or clarifying_questions or citations:
        return True
    return blocker in _FINDINGS_BLOCKERS or verdict in _FINDINGS_VERDICTS


def format_findings_comment(
    *,
    investigation_summary: str,
    unknowns: list[str],
    clarifying_questions: list[str],
    findings_reason: str = "",
    citations: list[str] | None = None,
) -> str:
    # Format here so PersistReplyInput.reply is investigation notes even if persist_as
    # is ignored during a rolling deploy.
    parts = ["Investigation notes"]
    if findings_reason:
        parts.extend(["", findings_reason])
    if investigation_summary:
        parts.extend(["", investigation_summary])
    if unknowns:
        parts.extend(["", "Still unknown:"])
        parts.extend(f"- {item}" for item in unknowns)
    if clarifying_questions:
        heading = (
            "Suggested questions for the customer:"
            if len(clarifying_questions) > 1
            else "Suggested question for the customer:"
        )
        parts.extend(["", heading])
        parts.extend(f"- {item}" for item in clarifying_questions[:MAX_CLARIFYING_QUESTIONS])
    refs = [ref for ref in (citations or []) if ref]
    if refs:
        parts.extend(["", "Sources:"])
        parts.extend(f"- {ref}" for ref in refs)
    return "\n".join(parts)
