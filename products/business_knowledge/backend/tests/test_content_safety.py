import asyncio
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic, safety
from products.business_knowledge.backend.models import KnowledgeDocument, KnowledgeSource, SafetyVerdict


class TestSafetyFilteringAndClassification(BaseTest):
    def _ready_text_source(self, name: str, text: str) -> tuple[KnowledgeSource, KnowledgeDocument]:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name=name, text=text)
        with team_scope(self.team.id, canonical=True):
            doc = KnowledgeDocument.objects.get(source_id=source.id)
        return source, doc

    def _ready_unknown_source(self, name: str, text: str) -> tuple[KnowledgeSource, KnowledgeDocument]:
        source, doc = self._ready_text_source(name, text)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(id=doc.id).update(safety_verdict=SafetyVerdict.UNKNOWN)
            doc.refresh_from_db()
        return source, doc

    def test_search_excludes_unsafe_documents(self) -> None:
        _source, doc = self._ready_text_source("Refunds", "Our refund policy covers widgets and gadgets.")

        assert logic.search_knowledge(self.team.id, "refund") != []

        logic.set_document_safety(team_id=self.team.id, document_id=doc.id, verdict=SafetyVerdict.UNSAFE, reason="x")
        assert logic.search_knowledge(self.team.id, "refund") == []

        logic.set_document_safety(team_id=self.team.id, document_id=doc.id, verdict=SafetyVerdict.SAFE)
        assert logic.search_knowledge(self.team.id, "refund") != []

    def test_search_excludes_unknown_documents(self) -> None:
        _source, doc = self._ready_text_source("Refunds", "Our refund policy covers widgets and gadgets.")
        assert logic.search_knowledge(self.team.id, "refund") != []

        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(id=doc.id).update(safety_verdict=SafetyVerdict.UNKNOWN)
        assert logic.search_knowledge(self.team.id, "refund") == []

    def test_pending_classification_lists_unknown_live_docs(self) -> None:
        _source, unknown_doc = self._ready_unknown_source("A", "alpha content here")
        _source_b, safe_doc = self._ready_text_source("B", "beta content here")

        pending_ids = {d.document_id for d in logic.list_documents_pending_classification()}
        assert unknown_doc.id in pending_ids
        assert safe_doc.id not in pending_ids

    def test_pending_classification_skips_tombstoned(self) -> None:
        _source, doc = self._ready_unknown_source("A", "alpha content here")
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(id=doc.id).update(tombstoned_at=timezone.now())
        assert logic.list_documents_pending_classification() == []

    def test_pending_classification_skips_orgs_without_ai_consent(self) -> None:
        _source, _doc = self._ready_unknown_source("A", "alpha content here")
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        assert logic.list_documents_pending_classification() == []


class TestSafetyClassifier(BaseTest):
    @parameterized.expand(
        [
            ("safe_plain", "SAFE", SafetyVerdict.SAFE, ""),
            ("unsafe_with_reason", "UNSAFE: prompt injection", SafetyVerdict.UNSAFE, "prompt injection"),
            ("unsafe_no_reason", "UNSAFE", SafetyVerdict.UNSAFE, ""),
            ("whitespace_safe", "  safe  ", SafetyVerdict.SAFE, ""),
        ]
    )
    def test_parse_verdict(self, _name: str, raw: str, expected_verdict: str, expected_reason: str) -> None:
        verdict, reason = safety._parse_verdict(raw)
        assert verdict == expected_verdict
        assert reason == expected_reason

    @override_settings(GEMINI_API_KEY="test-key")
    def test_classify_documents_routes_verdicts(self) -> None:
        docs = [
            logic.PendingDocument(
                team_id=self.team.id, document_id=UUID("00000000-0000-0000-0000-000000000001"), content="normal docs"
            ),
            logic.PendingDocument(
                team_id=self.team.id,
                document_id=UUID("00000000-0000-0000-0000-000000000002"),
                content="ATTACK ignore previous",
            ),
        ]

        async def fake_generate(model, contents, config):  # noqa: ANN001
            text = "UNSAFE: injection" if "ATTACK" in contents[0] else "SAFE"
            return type("Resp", (), {"text": text})()

        with patch.object(safety.genai, "AsyncClient") as mk:
            mk.return_value.models.generate_content = AsyncMock(side_effect=fake_generate)
            results = {r.document_id: r.verdict for r in asyncio.run(safety.classify_documents(docs))}

        assert results == {
            UUID("00000000-0000-0000-0000-000000000001"): SafetyVerdict.SAFE,
            UUID("00000000-0000-0000-0000-000000000002"): SafetyVerdict.UNSAFE,
        }

    @override_settings(GEMINI_API_KEY="test-key")
    def test_classify_documents_fails_open_on_error(self) -> None:
        docs = [
            logic.PendingDocument(
                team_id=self.team.id, document_id=UUID("00000000-0000-0000-0000-000000000001"), content="x"
            )
        ]
        with (
            patch.object(safety.genai, "AsyncClient") as mk,
            patch("products.business_knowledge.backend.safety.asyncio.sleep", AsyncMock()),
        ):
            mk.return_value.models.generate_content = AsyncMock(side_effect=RuntimeError("boom"))
            results = asyncio.run(safety.classify_documents(docs))

        assert results[0].verdict == SafetyVerdict.SAFE
