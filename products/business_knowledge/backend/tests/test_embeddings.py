import datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.constants import (
    BK_EMBEDDING_DOCUMENT_TYPE,
    BK_EMBEDDING_MODEL,
    BK_EMBEDDING_PRODUCT,
    EMBEDDING_STABLE_TS_MAX_AGE,
    EMBEDDING_TTL_REFRESH_WINDOW,
)
from products.business_knowledge.backend.models import (
    KnowledgeDocument,
    KnowledgeSource,
    SafetyVerdict,
    SourceStatus,
    SourceType,
)
from products.business_knowledge.backend.temporal import coordinator


class TestPendingEmbeddingSelection(BaseTest):
    def _safe_source(self, name: str, text: str) -> tuple[KnowledgeSource, KnowledgeDocument]:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name=name, text=text)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
            doc = KnowledgeDocument.objects.get(source_id=source.id)
        return source, doc

    def _set(self, doc: KnowledgeDocument, **fields: object) -> None:
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(id=doc.id).update(**fields)

    def _set_source(self, source: KnowledgeSource, **fields: object) -> None:
        with team_scope(self.team.id, canonical=True):
            KnowledgeSource.objects.filter(id=source.id).update(**fields)

    def _disapprove_org(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

    def test_lists_safe_unembedded_docs_with_chunks(self) -> None:
        _source, doc = self._safe_source("Refunds", "Our refund policy covers widgets and gadgets.")

        pending = logic.list_documents_pending_embedding()
        ids = {d.document_id for d in pending}
        assert doc.id in ids
        entry = next(d for d in pending if d.document_id == doc.id)
        # Young doc: uses the stable created_at timestamp for sort-key dedup.
        assert entry.timestamp == doc.created_at
        assert len(entry.chunks) >= 1
        assert all(c.content for c in entry.chunks)

    def test_old_doc_uses_fresh_timestamp(self) -> None:
        _source, doc = self._safe_source("Refunds", "Our refund policy covers widgets and gadgets.")
        # Past the stable-timestamp max age (TTL - refresh window): the row
        # would expire before the refresh cron re-emits, so now() must be used.
        old_created = timezone.now() - EMBEDDING_STABLE_TS_MAX_AGE - datetime.timedelta(days=10)
        self._set(doc, created_at=old_created)

        before = timezone.now()
        pending = logic.list_documents_pending_embedding()
        entry = next(d for d in pending if d.document_id == doc.id)
        assert entry.timestamp >= before

    def test_doc_within_max_age_keeps_created_at(self) -> None:
        _source, doc = self._safe_source("Refunds", "Our refund policy covers widgets and gadgets.")
        # Just inside the max age: stable created_at is still safe (the row
        # outlives the refresh cron's next pass) and keeps sort-key dedup.
        recent_created = timezone.now() - EMBEDDING_STABLE_TS_MAX_AGE + datetime.timedelta(days=1)
        self._set(doc, created_at=recent_created)

        entry = next(d for d in logic.list_documents_pending_embedding() if d.document_id == doc.id)
        assert entry.timestamp == recent_created

    @parameterized.expand(
        [
            # Only SAFE, approved, READY, live, not-yet-emitted docs are embedded.
            # Each case mutates exactly one of those preconditions and asserts the
            # doc drops out of the pending set.
            ("already_emitted", lambda t, s, d: t._set(d, embeddings_emitted_at=timezone.now())),
            ("unknown_verdict", lambda t, s, d: t._set(d, safety_verdict=SafetyVerdict.UNKNOWN)),
            ("unsafe_verdict", lambda t, s, d: t._set(d, safety_verdict=SafetyVerdict.UNSAFE)),
            ("tombstoned", lambda t, s, d: t._set(d, tombstoned_at=timezone.now())),
            ("source_not_ready", lambda t, s, d: t._set_source(s, status=SourceStatus.PROCESSING)),
            ("org_not_approved", lambda t, s, d: t._disapprove_org()),
        ]
    )
    def test_doc_excluded_from_pending(self, _name: str, mutate) -> None:  # noqa: ANN001
        source, doc = self._safe_source("Refunds", "Our refund policy covers widgets and gadgets.")
        mutate(self, source, doc)
        assert doc.id not in {d.document_id for d in logic.list_documents_pending_embedding()}

    def test_respects_cap(self) -> None:
        for i in range(3):
            self._safe_source(f"src{i}", f"content number {i} about refunds")
        assert len(logic.list_documents_pending_embedding(limit=2)) == 2


class TestMarkAndClearEmission(BaseTest):
    def _doc(self, verdict: str) -> KnowledgeDocument:
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="A", text="alpha content here"
        )
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=verdict)
            return KnowledgeDocument.objects.get(source_id=source.id)

    @parameterized.expand(
        [
            # The stamp guard is the second SAFE-only gate: even if a non-SAFE doc
            # somehow reaches mark (e.g. it flipped verdict mid-pass), it must not
            # be recorded as emitted.
            ("safe", SafetyVerdict.SAFE, True),
            ("unknown", SafetyVerdict.UNKNOWN, False),
            ("unsafe", SafetyVerdict.UNSAFE, False),
        ]
    )
    def test_mark_only_stamps_safe_docs(self, _name: str, verdict: str, should_stamp: bool) -> None:
        doc = self._doc(verdict)
        logic.mark_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            doc.refresh_from_db()
        assert (doc.embeddings_emitted_at is not None) is should_stamp

    def test_mark_is_idempotent(self) -> None:
        doc = self._doc(SafetyVerdict.SAFE)
        logic.mark_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            doc.refresh_from_db()
        first = doc.embeddings_emitted_at
        logic.mark_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            doc.refresh_from_db()
        assert doc.embeddings_emitted_at == first

    def test_clear_renulls(self) -> None:
        doc = self._doc(SafetyVerdict.SAFE)
        logic.mark_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        logic.clear_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            doc.refresh_from_db()
        assert doc.embeddings_emitted_at is None


class TestContentChangeResetsEmission(BaseTest):
    def test_crawl_upsert_clears_emission_stamp(self) -> None:
        # A crawl refresh that replaces a doc's content in place (same id) must
        # clear the emission stamp so the new content re-embeds once re-classified.
        with team_scope(self.team.id, canonical=True):
            source = KnowledgeSource.objects.create(
                team=self.team,
                name="Docs",
                source_type=SourceType.URL,
                status=SourceStatus.READY,
                source_url="https://example.com",
            )
            doc = KnowledgeDocument.objects.create(
                team=self.team,
                source=source,
                stable_id="https://example.com",
                title="Old title",
                content="Original content about refunds.",
                url="https://example.com",
                content_hash="old-hash",
                safety_verdict=SafetyVerdict.SAFE,
                embeddings_emitted_at=timezone.now(),
            )

            logic._insert_document_and_chunks(
                source=source,
                team_id=self.team.id,
                title="New title",
                text="Completely new content about returns and exchanges.",
                url="https://example.com",
                etag="new-etag",
                content_hash="new-hash",
                existing_doc=doc,
            )
            doc.refresh_from_db()

        assert doc.safety_verdict == SafetyVerdict.UNKNOWN
        assert doc.embeddings_emitted_at is None


class TestEmitOneDocument(BaseTest):
    # Tests the sync produce+stamp primitive directly. The async activity is a
    # thin gather/try-except wrapper over this; the threaded-DB visibility that
    # async activity tests need (committed transactions) isn't worth dragging in
    # for glue that just counts results.
    def _pending(self, name: str, text: str) -> tuple[KnowledgeDocument, logic.DocumentToEmbed]:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name=name, text=text)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
            doc = KnowledgeDocument.objects.get(source_id=source.id)
        entry = next(d for d in logic.list_documents_pending_embedding() if d.document_id == doc.id)
        return doc, entry

    def test_emits_each_chunk_and_stamps(self) -> None:
        doc, entry = self._pending("Refunds", "Our refund policy covers widgets and gadgets.")

        with patch.object(coordinator, "emit_embedding_request") as emit:
            written = coordinator._emit_one_document(entry)

        assert written == len(entry.chunks)
        assert emit.call_count == len(entry.chunks)
        emitted_doc_ids = {call.kwargs["document_id"] for call in emit.call_args_list}
        assert emitted_doc_ids == {str(c.chunk_id) for c in entry.chunks}
        kwargs = emit.call_args_list[0].kwargs
        assert kwargs["product"] == BK_EMBEDDING_PRODUCT
        assert kwargs["document_type"] == BK_EMBEDDING_DOCUMENT_TYPE
        assert kwargs["models"] == [BK_EMBEDDING_MODEL]
        assert kwargs["timestamp"] == doc.created_at  # stable doc timestamp, not now()
        assert kwargs["metadata"]["document_id"] == str(doc.id)

        with team_scope(self.team.id, canonical=True):
            doc.refresh_from_db()
        assert doc.embeddings_emitted_at is not None

    def test_emits_old_doc_with_fresh_timestamp(self) -> None:
        doc, entry = self._pending("Refunds", "Our refund policy covers widgets and gadgets.")
        old_created = timezone.now() - EMBEDDING_STABLE_TS_MAX_AGE - datetime.timedelta(days=10)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(id=doc.id).update(created_at=old_created, embeddings_emitted_at=None)
        before = timezone.now()
        entry = next(d for d in logic.list_documents_pending_embedding() if d.document_id == doc.id)

        with patch.object(coordinator, "emit_embedding_request") as emit:
            coordinator._emit_one_document(entry)

        kwargs = emit.call_args_list[0].kwargs
        assert kwargs["timestamp"] >= before

    def test_emit_failure_propagates_and_leaves_doc_unstamped(self) -> None:
        doc, entry = self._pending("Refunds", "Our refund policy covers widgets and gadgets.")

        with patch.object(coordinator, "emit_embedding_request", side_effect=RuntimeError("kafka down")):
            with self.assertRaises(RuntimeError):
                coordinator._emit_one_document(entry)

        with team_scope(self.team.id, canonical=True):
            doc.refresh_from_db()
        assert doc.embeddings_emitted_at is None
        # Still pending so the next pass retries the whole doc.
        assert doc.id in {d.document_id for d in logic.list_documents_pending_embedding()}


class TestReconciliationSelection(BaseTest):
    def _emitted_doc(self, *, emitted_minutes_ago: int, verdict: str = SafetyVerdict.SAFE) -> KnowledgeDocument:
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="A", text="alpha content about refunds"
        )
        emitted_at = timezone.now() - datetime.timedelta(minutes=emitted_minutes_ago)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(
                safety_verdict=verdict, embeddings_emitted_at=emitted_at
            )
            return KnowledgeDocument.objects.get(source_id=source.id)

    def test_returns_old_emitted_safe_docs_with_chunk_ids(self) -> None:
        old = self._emitted_doc(emitted_minutes_ago=60 * 24)
        recent = self._emitted_doc(emitted_minutes_ago=1)

        result = logic.list_documents_for_embedding_reconciliation()
        ids = {d.document_id for d in result}
        assert old.id in ids
        assert recent.id not in ids  # still within the grace window
        entry = next(d for d in result if d.document_id == old.id)
        assert len(entry.chunk_ids) >= 1

    @parameterized.expand(
        [
            ("unknown", SafetyVerdict.UNKNOWN),
            ("unsafe", SafetyVerdict.UNSAFE),
        ]
    )
    def test_excludes_non_safe_emitted(self, _name: str, verdict: str) -> None:
        # Reconciliation only re-checks docs that are still embeddable (SAFE);
        # a doc that left SAFE shouldn't be re-emitted.
        doc = self._emitted_doc(emitted_minutes_ago=60 * 24, verdict=verdict)
        assert doc.id not in {d.document_id for d in logic.list_documents_for_embedding_reconciliation()}

    def test_orders_oldest_emitted_first(self) -> None:
        older = self._emitted_doc(emitted_minutes_ago=60 * 48)
        newer = self._emitted_doc(emitted_minutes_ago=60 * 24)
        order = [d.document_id for d in logic.list_documents_for_embedding_reconciliation()]
        assert order.index(older.id) < order.index(newer.id)


class TestTtlRefreshSelection(BaseTest):
    def _emitted_doc(self, *, emitted_days_ago: float, verdict: str = SafetyVerdict.SAFE) -> KnowledgeDocument:
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="A", text="alpha content about refunds"
        )
        emitted_at = timezone.now() - datetime.timedelta(days=emitted_days_ago)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(
                safety_verdict=verdict, embeddings_emitted_at=emitted_at
            )
            return KnowledgeDocument.objects.get(source_id=source.id)

    def test_selects_only_docs_past_the_window(self) -> None:
        window_days = EMBEDDING_TTL_REFRESH_WINDOW.days
        aging = self._emitted_doc(emitted_days_ago=window_days + 5)
        fresh = self._emitted_doc(emitted_days_ago=window_days - 5)

        ids = {d.document_id for d in logic.list_documents_for_embedding_refresh()}
        assert aging.id in ids
        assert fresh.id not in ids

    def test_never_emitted_doc_is_not_refreshed(self) -> None:
        # embeddings_emitted_at IS NULL belongs to the pending-emit path, not the
        # refresh path — refresh only re-emits docs that were already stamped.
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="A", text="alpha content about refunds"
        )
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
            doc = KnowledgeDocument.objects.get(source_id=source.id)
        assert doc.id not in {d.document_id for d in logic.list_documents_for_embedding_refresh()}

    @parameterized.expand(
        [
            ("unknown", SafetyVerdict.UNKNOWN),
            ("unsafe", SafetyVerdict.UNSAFE),
        ]
    )
    def test_excludes_non_safe(self, _name: str, verdict: str) -> None:
        doc = self._emitted_doc(emitted_days_ago=EMBEDDING_TTL_REFRESH_WINDOW.days + 5, verdict=verdict)
        assert doc.id not in {d.document_id for d in logic.list_documents_for_embedding_refresh()}

    def test_uses_now_not_created_at_as_timestamp(self) -> None:
        # The TTL is on the embedding row timestamp, so the refresh must pass a
        # FRESH timestamp (now) — created_at would not reset the clock.
        doc = self._emitted_doc(emitted_days_ago=EMBEDDING_TTL_REFRESH_WINDOW.days + 5)
        entry = next(d for d in logic.list_documents_for_embedding_refresh() if d.document_id == doc.id)
        assert entry.timestamp != doc.created_at
        assert entry.timestamp > doc.created_at
        assert len(entry.chunks) >= 1

    def test_respects_cap(self) -> None:
        for _ in range(3):
            self._emitted_doc(emitted_days_ago=EMBEDDING_TTL_REFRESH_WINDOW.days + 5)
        assert len(logic.list_documents_for_embedding_refresh(limit=2)) == 2

    def test_orders_oldest_emitted_first(self) -> None:
        older = self._emitted_doc(emitted_days_ago=EMBEDDING_TTL_REFRESH_WINDOW.days + 30)
        newer = self._emitted_doc(emitted_days_ago=EMBEDDING_TTL_REFRESH_WINDOW.days + 5)
        order = [d.document_id for d in logic.list_documents_for_embedding_refresh()]
        assert order.index(older.id) < order.index(newer.id)


class TestRestampAndReemit(BaseTest):
    def _safe_emitted_doc(self) -> KnowledgeDocument:
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name="A", text="alpha content about refunds"
        )
        old_stamp = timezone.now() - EMBEDDING_TTL_REFRESH_WINDOW - datetime.timedelta(days=5)
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(source_id=source.id).update(
                safety_verdict=SafetyVerdict.SAFE, embeddings_emitted_at=old_stamp
            )
            return KnowledgeDocument.objects.get(source_id=source.id)

    def test_restamp_moves_stamp_forward(self) -> None:
        doc = self._safe_emitted_doc()
        with team_scope(self.team.id, canonical=True):
            before = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at
        logic.restamp_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            after = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at
        assert after is not None and before is not None
        assert after > before

    @parameterized.expand(
        [
            ("unknown", SafetyVerdict.UNKNOWN),
            ("unsafe", SafetyVerdict.UNSAFE),
        ]
    )
    def test_restamp_skips_non_safe(self, _name: str, verdict: str) -> None:
        doc = self._safe_emitted_doc()
        with team_scope(self.team.id, canonical=True):
            before = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at
            KnowledgeDocument.objects.filter(id=doc.id).update(safety_verdict=verdict)
        logic.restamp_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            after = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at
        assert after == before

    def test_restamp_skips_renulled_doc(self) -> None:
        # A content change mid-pass NULLs the stamp; that new content must flow
        # through the pending-emit path, not be re-stamped by the refresh.
        doc = self._safe_emitted_doc()
        with team_scope(self.team.id, canonical=True):
            KnowledgeDocument.objects.filter(id=doc.id).update(embeddings_emitted_at=None)
        logic.restamp_document_embeddings_emitted(team_id=self.team.id, document_id=doc.id)
        with team_scope(self.team.id, canonical=True):
            assert KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at is None

    def test_reemit_produces_chunks_with_fresh_timestamp_and_restamps(self) -> None:
        doc = self._safe_emitted_doc()
        entry = next(d for d in logic.list_documents_for_embedding_refresh() if d.document_id == doc.id)
        with team_scope(self.team.id, canonical=True):
            before = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at

        with patch.object(coordinator, "emit_embedding_request") as emit:
            written = coordinator._reemit_one_document(entry)

        assert written == len(entry.chunks)
        assert emit.call_count == len(entry.chunks)
        kwargs = emit.call_args_list[0].kwargs
        assert kwargs["timestamp"] == entry.timestamp  # fresh now(), not created_at
        assert kwargs["timestamp"] != doc.created_at
        assert kwargs["metadata"]["document_id"] == str(doc.id)

        with team_scope(self.team.id, canonical=True):
            after = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at
        assert after is not None and before is not None
        assert after > before

    def test_reemit_failure_leaves_old_stamp(self) -> None:
        doc = self._safe_emitted_doc()
        entry = next(d for d in logic.list_documents_for_embedding_refresh() if d.document_id == doc.id)
        with team_scope(self.team.id, canonical=True):
            before = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at

        with patch.object(coordinator, "emit_embedding_request", side_effect=RuntimeError("kafka down")):
            with self.assertRaises(RuntimeError):
                coordinator._reemit_one_document(entry)

        with team_scope(self.team.id, canonical=True):
            after = KnowledgeDocument.objects.get(id=doc.id).embeddings_emitted_at
        # Stamp unchanged (no re-stamp), so the doc is retried on a later pass.
        assert after == before
