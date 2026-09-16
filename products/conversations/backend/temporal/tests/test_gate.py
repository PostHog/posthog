from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.temporal.ai_reply.gate import (
    decide_reply_action,
    findings_reason_for,
    should_persist_findings,
)
from products.conversations.backend.temporal.ai_reply.schemas import (
    DraftOutput,
    SupportReplyDraft,
    ValidateOutput,
    coerce_dataclass,
)


class TestFailClosedDefaults(SimpleTestCase):
    def test_omitted_draft_verdict_is_blocked_on_knowledge(self):
        draft = SupportReplyDraft(reply="ok", citations=[], confidence=0.9)
        assert draft.verdict == "blocked_on_knowledge"

    def test_unknown_draft_verdict_is_blocked_on_knowledge(self):
        draft = SupportReplyDraft(reply="ok", citations=[], confidence=0.9, verdict="idk")
        assert draft.verdict == "blocked_on_knowledge"

    def test_activity_defaults_do_not_auto_send(self):
        draft = DraftOutput(reply="Looks right.", citations=[], confidence=0.9)
        validate = ValidateOutput(grounded=True, coverage=0.9, confidence=0.9, missing=[])
        assert draft.verdict == "blocked_on_knowledge"
        assert validate.blocker == "knowledge"
        assert (
            decide_reply_action(
                grounded=validate.grounded,
                coverage=validate.coverage,
                validator_confidence=validate.confidence,
                draft_confidence=draft.confidence,
                blocker=validate.blocker,
                verdict=draft.verdict,
                attempt=0,
                max_attempts=2,
            )
            == "retry"
        )


class TestDecideReplyAction(SimpleTestCase):
    def _decide(
        self,
        *,
        grounded: bool = True,
        coverage: float = 0.9,
        validator_confidence: float = 0.9,
        draft_confidence: float = 0.9,
        blocker: str = "none",
        verdict: str = "answerable",
        attempt: int = 0,
        max_attempts: int = 2,
    ):
        return decide_reply_action(
            grounded=grounded,
            coverage=coverage,
            validator_confidence=validator_confidence,
            draft_confidence=draft_confidence,
            blocker=blocker,
            verdict=verdict,
            attempt=attempt,
            max_attempts=max_attempts,
        )

    def test_auto_send_when_both_judges_agree(self):
        assert self._decide() == "auto_send"

    def test_validator_high_draft_low_does_not_auto_send(self):
        assert self._decide(draft_confidence=0.3) == "suggest"

    def test_ungrounded_never_auto_sends(self):
        assert self._decide(grounded=False, validator_confidence=0.9, draft_confidence=0.9) == "findings"

    def test_low_coverage_never_auto_sends(self):
        assert self._decide(coverage=0.7) == "suggest"

    def test_customer_info_exits_to_clarify_before_suggest(self):
        assert self._decide(blocker="customer_info", validator_confidence=0.6) == "clarify"

    def test_blocked_on_customer_verdict_exits_to_clarify(self):
        assert self._decide(verdict="blocked_on_customer", blocker="none") == "clarify"

    def test_knowledge_retries_on_first_attempt(self):
        assert self._decide(blocker="knowledge", grounded=False, validator_confidence=0.2) == "retry"

    def test_blocked_on_knowledge_without_knowledge_blocker_does_not_retry(self):
        assert self._decide(verdict="blocked_on_knowledge", blocker="none", validator_confidence=0.6) == "findings"

    def test_knowledge_does_not_retry_on_last_attempt(self):
        assert (
            self._decide(blocker="knowledge", grounded=False, validator_confidence=0.2, attempt=1, max_attempts=2)
            == "findings"
        )

    def test_knowledge_does_not_suggest_after_retry(self):
        assert self._decide(blocker="knowledge", validator_confidence=0.6, attempt=1, max_attempts=2) == "findings"

    def test_blocked_on_knowledge_does_not_suggest(self):
        assert (
            self._decide(
                verdict="blocked_on_knowledge",
                blocker="none",
                validator_confidence=0.6,
                attempt=1,
                max_attempts=2,
            )
            == "findings"
        )

    @parameterized.expand(
        [
            ("contradiction", {"blocker": "contradiction"}, "findings"),
            ("out_of_scope", {"verdict": "out_of_scope"}, "findings"),
        ]
    )
    def test_terminal_findings_blockers(self, _name, overrides, expected):
        assert self._decide(**overrides) == expected


class TestFindingsNote(SimpleTestCase):
    def test_knowledge_blocker_persists_even_without_investigation_text(self):
        assert should_persist_findings(
            investigation_summary="",
            unknowns=[],
            clarifying_questions=[],
            citations=[],
            blocker="knowledge",
            verdict="answerable",
        )
        assert findings_reason_for(blocker="knowledge", verdict="answerable", grounded=False) == (
            "The knowledge base and docs did not cover this."
        )

    def test_ungrounded_cited_draft_persists_findings(self):
        assert should_persist_findings(
            investigation_summary="",
            unknowns=[],
            clarifying_questions=[],
            citations=["https://example.com/docs"],
            blocker="none",
            verdict="answerable",
        )
        assert findings_reason_for(blocker="none", verdict="answerable", grounded=False) == (
            "This draft does not match the sources, so it was not sent."
        )

    def test_empty_ungrounded_draft_does_not_persist_findings(self):
        assert not should_persist_findings(
            investigation_summary="",
            unknowns=[],
            clarifying_questions=[],
            citations=[],
            blocker="none",
            verdict="answerable",
        )


class TestCoerceActivityResults(SimpleTestCase):
    def test_dict_without_verdict_fails_closed(self):
        draft = coerce_dataclass(DraftOutput, {"reply": "ok", "citations": [], "confidence": 0.9})
        assert draft.verdict == "blocked_on_knowledge"
        assert draft.unknowns == []
        assert draft.investigation_summary == ""

    def test_dict_without_blocker_fails_closed(self):
        validate = coerce_dataclass(
            ValidateOutput, {"grounded": True, "coverage": 0.9, "confidence": 0.9, "missing": []}
        )
        assert validate.blocker == "knowledge"

    def test_legacy_json_payload_decodes_with_defaults(self):
        import json

        from temporalio.api.common.v1 import Payload
        from temporalio.converter import JSONPlainPayloadConverter

        converter = JSONPlainPayloadConverter()
        payload = Payload(
            metadata={"encoding": b"json/plain"},
            data=json.dumps(
                {"reply": "ok", "citations": [], "confidence": 0.9, "sources": [], "task_run_id": ""}
            ).encode(),
        )
        decoded = coerce_dataclass(DraftOutput, converter.from_payload(payload, DraftOutput))
        assert decoded.verdict == "blocked_on_knowledge"
        assert decoded.sandbox_seconds == 0.0
