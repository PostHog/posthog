import asyncio
from datetime import UTC, datetime
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.business_knowledge.backend import billing, logic
from products.business_knowledge.backend.facade import api as facade_api
from products.business_knowledge.backend.llm_telemetry import RetrievalTrace, stable_trace_id
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeLibrary,
    KnowledgeUsageKey,
    KnowledgeUsageRecord,
)

TEXT = "Refunds are available within 30 days.\n\nShipping is free above 50 euros."


class _UsageTest(BaseTest):
    def _rows(self, usage_key: KnowledgeUsageKey, team_id: int | None = None) -> list[KnowledgeUsageRecord]:
        return list(
            KnowledgeUsageRecord.objects.unscoped()
            .filter(team_id=team_id or self.team.id, usage_key=usage_key)
            .order_by("created_at")
        )


class TestIngestionMetering(_UsageTest):
    def test_text_source_meters_every_chunk_it_writes(self) -> None:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Policies", text=TEXT)

        chunks = KnowledgeChunk.objects.unscoped().filter(source_id=source.id).count()
        assert chunks > 0
        assert [(r.quantity, r.surface, r.source_id) for r in self._rows(KnowledgeUsageKey.CHUNKS)] == [
            (chunks, "text", source.id)
        ]

    def test_editing_text_meters_the_new_chunks_again(self) -> None:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Policies", text=TEXT)

        logic.update_text_source(source_id=source.id, team_id=self.team.id, name=None, text=TEXT + "\n\nUpdated.")

        assert len(self._rows(KnowledgeUsageKey.CHUNKS)) == 2

    def test_learned_source_meters_as_generated_ingestion(self) -> None:
        result = logic.create_generated_knowledge_document(
            logic.CreateGeneratedKnowledgeDocument(
                team_id=self.team.id,
                provider="conversations",
                ticket_id=UUID("10000000-0000-0000-0000-000000000001"),
                ticket_number=42,
                source_team_id=self.team.id,
                resolution_comment_id=UUID("20000000-0000-0000-0000-000000000002"),
                analysis_version="post_resolution_v1",
                title="Refund policy",
                content="Refunds are available within 30 days.",
                evidence_revision_at=timezone.now(),
            )
        )

        rows = self._rows(KnowledgeUsageKey.CHUNKS)
        assert [(r.surface, r.source_id) for r in rows] == [("generated", result.source_id)]

    def test_a_rolled_back_write_meters_nothing(self) -> None:
        with self.assertRaises(RuntimeError), transaction.atomic():
            billing.record_chunks_ingested(
                team_id=self.team.id, quantity=3, surface="text", source_id=None, document_id=None
            )
            raise RuntimeError("rolled back")

        assert self._rows(KnowledgeUsageKey.CHUNKS) == []

    def test_zero_chunks_write_no_row(self) -> None:
        billing.record_chunks_ingested(
            team_id=self.team.id, quantity=0, surface="text", source_id=None, document_id=None
        )

        assert self._rows(KnowledgeUsageKey.CHUNKS) == []

    def test_a_metering_failure_does_not_fail_the_ingest(self) -> None:
        with patch.object(KnowledgeUsageRecord.objects, "unscoped", side_effect=RuntimeError("ledger down")):
            source = logic.create_text_source(
                team_id=self.team.id, created_by_id=self.user.id, name="Policies", text=TEXT
            )

        assert KnowledgeChunk.objects.unscoped().filter(source_id=source.id).exists()
        assert self._rows(KnowledgeUsageKey.CHUNKS) == []


class TestRetrievalMetering(_UsageTest):
    def test_a_search_with_a_trace_meters_one_query(self) -> None:
        trace = RetrievalTrace(surface="api")

        logic.search_knowledge(self.team.id, "refunds", trace=trace)

        assert [(r.quantity, r.surface, r.idempotency_key) for r in self._rows(KnowledgeUsageKey.QUERIES)] == [
            (1, "api", trace.trace_id)
        ]

    def test_a_search_without_a_trace_is_not_metered(self) -> None:
        logic.search_knowledge(self.team.id, "refunds")

        assert self._rows(KnowledgeUsageKey.QUERIES) == []

    def test_the_internal_docs_shadow_search_is_not_metered(self) -> None:
        logic.search_knowledge(self.team.id, "refunds", trace=RetrievalTrace(surface="docs_shadow"))

        assert self._rows(KnowledgeUsageKey.QUERIES) == []

    def test_a_retried_search_with_the_same_trace_meters_once(self) -> None:
        trace = RetrievalTrace(surface="support", trace_id=stable_trace_id("workflow", "run", "activity", 0, "refunds"))

        logic.search_knowledge(self.team.id, "refunds", trace=trace)
        logic.search_knowledge(self.team.id, "refunds", trace=trace)

        assert len(self._rows(KnowledgeUsageKey.QUERIES)) == 1

    def test_a_search_against_an_empty_library_is_metered(self) -> None:
        with team_scope(self.team.id, canonical=True):
            library = KnowledgeLibrary.objects.create(team_id=self.team.id, name="Empty")
        trace = RetrievalTrace(surface="api")

        results = logic.search_knowledge_for_team(self.team, "refunds", trace=trace, library_id=library.id)

        assert results == []
        assert [r.idempotency_key for r in self._rows(KnowledgeUsageKey.QUERIES)] == [trace.trace_id]

    def test_a_search_that_raises_meters_nothing(self) -> None:
        with (
            patch.object(logic, "_search_knowledge", side_effect=RuntimeError("search failed")),
            self.assertRaises(RuntimeError),
        ):
            logic.search_knowledge(self.team.id, "refunds", trace=RetrievalTrace(surface="api"))

        assert self._rows(KnowledgeUsageKey.QUERIES) == []

    def test_a_metering_failure_does_not_fail_the_search(self) -> None:
        with patch.object(KnowledgeUsageRecord.objects, "unscoped", side_effect=RuntimeError("ledger down")):
            results = logic.search_knowledge(self.team.id, "refunds", trace=RetrievalTrace(surface="api"))

        assert results == []

    def test_sync_search_from_a_child_environment_meters_the_parent(self) -> None:
        child = Team.objects.create(
            organization=self.organization, parent_team=self.team, project=self.team.project, name="Child environment"
        )

        with patch.object(logic, "generate_embedding", side_effect=RuntimeError("no embeddings")):
            logic.search_knowledge_for_team(child, "refunds", trace=RetrievalTrace(surface="api"))

        assert len(self._rows(KnowledgeUsageKey.QUERIES)) == 1
        assert self._rows(KnowledgeUsageKey.QUERIES, team_id=child.id) == []

    def test_async_search_from_a_child_environment_searches_the_child_and_meters_the_parent(self) -> None:
        # PostHog AI only authorizes the environment it runs in, so the search must not widen to the parent.
        child = Team.objects.create(
            organization=self.organization, parent_team=self.team, project=self.team.project, name="Child environment"
        )

        def run_inline(fn, **_kwargs):
            async def call(*args, **kwargs):
                return fn(*args, **kwargs)

            return call

        with (
            patch.object(logic, "database_sync_to_async", side_effect=run_inline),
            patch.object(logic, "resolve_effective_team_id", return_value=self.team.id),
            patch.object(logic, "async_generate_embedding", side_effect=RuntimeError("no embeddings")),
            patch.object(logic, "_search_knowledge", return_value=[]) as search,
            patch.object(billing, "record_query") as record_query,
        ):
            asyncio.run(
                logic.async_search_knowledge_for_team(child, "refunds", trace=RetrievalTrace(surface="posthog_ai"))
            )

        assert search.call_args.args[0] == child.id
        assert record_query.call_args.kwargs["team_id"] == self.team.id

    def test_stable_trace_ids_repeat_for_the_same_parts_only(self) -> None:
        assert stable_trace_id("a", 1) == stable_trace_id("a", 1)
        assert stable_trace_id("a", 1) != stable_trace_id("a", 2)


class TestUsageByTeam(_UsageTest):
    PERIOD_START = datetime(2026, 1, 2, tzinfo=UTC)
    PERIOD_END = datetime(2026, 1, 3, tzinfo=UTC)

    def _record(self, usage_key: KnowledgeUsageKey, quantity: int, created_at: datetime, team_id: int) -> None:
        row = KnowledgeUsageRecord.objects.unscoped().create(
            team_id=team_id, usage_key=usage_key, quantity=quantity, surface="text"
        )
        # `created_at` is set on insert, so move the row into the period afterwards.
        KnowledgeUsageRecord.objects.unscoped().filter(id=row.id).update(created_at=created_at)

    def test_sums_each_meter_per_team_for_rows_written_in_the_period(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other project")
        inside = datetime(2026, 1, 2, 12, tzinfo=UTC)
        self._record(KnowledgeUsageKey.CHUNKS, 3, inside, self.team.id)
        self._record(KnowledgeUsageKey.CHUNKS, 4, inside, self.team.id)
        self._record(KnowledgeUsageKey.QUERIES, 1, inside, self.team.id)
        self._record(KnowledgeUsageKey.QUERIES, 1, inside, other.id)
        self._record(KnowledgeUsageKey.CHUNKS, 9, datetime(2026, 1, 1, 23, 59, tzinfo=UTC), self.team.id)
        self._record(KnowledgeUsageKey.QUERIES, 1, self.PERIOD_END, self.team.id)

        usage = facade_api.get_usage_by_team(self.PERIOD_START, self.PERIOD_END)

        assert usage.chunks == [(self.team.id, 7)]
        assert sorted(usage.queries) == sorted([(self.team.id, 1), (other.id, 1)])

    def test_no_usage_returns_empty_meters(self) -> None:
        usage = facade_api.get_usage_by_team(self.PERIOD_START, self.PERIOD_END)

        assert usage.chunks == []
        assert usage.queries == []
