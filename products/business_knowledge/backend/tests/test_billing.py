import asyncio
from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team
from posthog.usage_ingestion.client import UsageRecord

from products.business_knowledge.backend import billing, logic, quota
from products.business_knowledge.backend.llm_telemetry import RetrievalTrace, stable_trace_id
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeSource,
    KnowledgeUsageKey,
    KnowledgeUsageRecord,
    SourceStatus,
    SourceType,
)

TEXT = "Refunds are available within 30 days.\n\nShipping is free above 50 euros."
INGESTION_LIMITED = "products.business_knowledge.backend.quota.is_ingestion_limited"
RETRIEVAL_LIMITED = "products.business_knowledge.backend.quota.is_retrieval_limited"


class _BillingTest(APIBaseTest):
    def _rows(self, usage_key: KnowledgeUsageKey) -> list[KnowledgeUsageRecord]:
        return list(
            KnowledgeUsageRecord.objects.unscoped()
            .filter(team_id=self.team.id, usage_key=usage_key)
            .order_by("created_at")
        )

    def _generated_input(
        self, content: str = "Refunds are available within 30 days."
    ) -> logic.CreateGeneratedKnowledgeDocument:
        return logic.CreateGeneratedKnowledgeDocument(
            team_id=self.team.id,
            provider="conversations",
            ticket_id=UUID("10000000-0000-0000-0000-000000000001"),
            ticket_number=42,
            source_team_id=self.team.id,
            resolution_comment_id=UUID("20000000-0000-0000-0000-000000000002"),
            analysis_version="post_resolution_v1",
            title="Refund policy",
            content=content,
            evidence_revision_at=timezone.now(),
        )


class TestIngestionBilling(_BillingTest):
    def test_text_source_bills_every_chunk_it_writes(self) -> None:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Policies", text=TEXT)

        chunks = KnowledgeChunk.objects.unscoped().filter(source_id=source.id).count()
        assert chunks > 0
        assert [(r.quantity, r.surface, r.source_id) for r in self._rows(KnowledgeUsageKey.CHUNKS)] == [
            (chunks, "text", source.id)
        ]

    def test_editing_text_bills_the_new_chunks_again(self) -> None:
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Policies", text=TEXT)

        logic.update_text_source(source_id=source.id, team_id=self.team.id, name=None, text=TEXT + "\n\nUpdated.")

        assert len(self._rows(KnowledgeUsageKey.CHUNKS)) == 2

    def test_learned_source_bills_as_generated_ingestion(self) -> None:
        result = logic.create_generated_knowledge_document(self._generated_input())

        rows = self._rows(KnowledgeUsageKey.CHUNKS)
        assert [(r.surface, r.source_id) for r in rows] == [("generated", result.source_id)]

    def test_a_rolled_back_write_bills_nothing(self) -> None:
        with self.assertRaises(RuntimeError), transaction.atomic():
            billing.record_chunks_ingested(
                team_id=self.team.id, quantity=3, surface="text", source_id=None, document_id=None
            )
            raise RuntimeError("rolled back")

        assert self._rows(KnowledgeUsageKey.CHUNKS) == []

    def test_chunks_are_mirrored_to_usage_ingestion_after_commit(self) -> None:
        with (
            patch.object(billing, "report_usage") as report_usage,
            patch.object(billing, "_enqueue", side_effect=billing._send),
            self.captureOnCommitCallbacks(execute=True),
        ):
            billing.record_chunks_ingested(
                team_id=self.team.id, quantity=3, surface="text", source_id=None, document_id=None
            )

        row = self._rows(KnowledgeUsageKey.CHUNKS)[0]
        [records] = report_usage.call_args.args
        assert [(r.record_id, r.producer_id, r.team_id, r.usage_key, r.unit, r.quantity) for r in records] == [
            (str(row.id), "business-knowledge", self.team.id, "business_knowledge_chunks", "chunks", 3)
        ]
        assert isinstance(records[0], UsageRecord)

    def test_ingestion_limit_blocks_text_sources_before_anything_is_written(self) -> None:
        with patch(INGESTION_LIMITED, return_value=True), self.assertRaises(logic.IngestionLimitedError):
            logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Policies", text=TEXT)

        assert self._rows(KnowledgeUsageKey.CHUNKS) == []
        assert not KnowledgeChunk.objects.unscoped().filter(team_id=self.team.id).exists()


class TestRetrievalBilling(_BillingTest):
    def test_a_search_with_a_trace_bills_one_query(self) -> None:
        trace = RetrievalTrace(surface="api")

        logic.search_knowledge(self.team.id, "refunds", trace=trace)

        assert [(r.quantity, r.surface, r.idempotency_key) for r in self._rows(KnowledgeUsageKey.QUERIES)] == [
            (1, "api", trace.trace_id)
        ]

    def test_a_search_without_a_trace_is_not_billed(self) -> None:
        # Only offline evals and tests search without a trace.
        logic.search_knowledge(self.team.id, "refunds")

        assert self._rows(KnowledgeUsageKey.QUERIES) == []

    def test_a_retried_search_with_the_same_trace_bills_once(self) -> None:
        trace = RetrievalTrace(surface="support", trace_id=stable_trace_id("workflow", "run", "activity", 0, "refunds"))

        logic.search_knowledge(self.team.id, "refunds", trace=trace)
        logic.search_knowledge(self.team.id, "refunds", trace=trace)

        assert len(self._rows(KnowledgeUsageKey.QUERIES)) == 1

    def test_a_retried_search_is_mirrored_once(self) -> None:
        trace = RetrievalTrace(surface="support", trace_id=stable_trace_id("workflow", "run", "activity", 0, "refunds"))

        with (
            patch.object(billing, "report_usage") as report_usage,
            patch.object(billing, "_enqueue", side_effect=billing._send),
            self.captureOnCommitCallbacks(execute=True),
        ):
            logic.search_knowledge(self.team.id, "refunds", trace=trace)
            logic.search_knowledge(self.team.id, "refunds", trace=trace)

        assert report_usage.call_count == 1
        [records] = report_usage.call_args.args
        assert [(r.record_id, r.usage_key, r.quantity) for r in records] == [
            (trace.trace_id, "business_knowledge_queries", 1)
        ]

    def test_a_search_that_raises_bills_nothing(self) -> None:
        with (
            patch.object(logic, "_search_knowledge", side_effect=RuntimeError("search failed")),
            self.assertRaises(RuntimeError),
        ):
            logic.search_knowledge(self.team.id, "refunds", trace=RetrievalTrace(surface="api"))

        assert self._rows(KnowledgeUsageKey.QUERIES) == []

    def test_retrieval_limit_refuses_the_search_and_bills_nothing(self) -> None:
        with patch(RETRIEVAL_LIMITED, return_value=True), self.assertRaises(logic.RetrievalLimitedError):
            logic.search_knowledge_for_team(self.team, "refunds", trace=RetrievalTrace(surface="api"))

        assert self._rows(KnowledgeUsageKey.QUERIES) == []

    def test_async_search_from_a_child_environment_searches_the_child_and_bills_the_parent(self) -> None:
        # PostHog AI only authorizes the environment it runs in, so the search must not widen to the parent
        # project. Quota and billing still belong to the parent, where usage is counted.
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
            patch.object(logic, "_ensure_retrieval_allowed") as ensure_allowed,
            patch.object(logic, "async_generate_embedding", side_effect=RuntimeError("no embeddings")),
            patch.object(logic, "_search_knowledge", return_value=[]) as search,
            patch.object(billing, "record_query") as record_query,
        ):
            asyncio.run(
                logic.async_search_knowledge_for_team(child, "refunds", trace=RetrievalTrace(surface="posthog_ai"))
            )

        ensure_allowed.assert_called_once_with(self.team.id, child.api_token)
        assert search.call_args.args[0] == child.id
        assert record_query.call_args.kwargs["team_id"] == self.team.id

    def test_stable_trace_ids_repeat_for_the_same_parts_only(self) -> None:
        assert stable_trace_id("a", 1) == stable_trace_id("a", 1)
        assert stable_trace_id("a", 1) != stable_trace_id("a", 2)


class TestUrlSourceEditsAtTheLimit(_BillingTest):
    def test_a_recrawl_edit_is_refused_before_the_new_url_is_saved(self) -> None:
        source = KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="Docs",
            source_type=SourceType.URL,
            source_url="https://docs.example.com/old",
            status=SourceStatus.READY,
        )

        with (
            patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None)),
            patch(INGESTION_LIMITED, return_value=True),
            self.assertRaises(logic.IngestionLimitedError),
        ):
            logic.update_url_source(source_id=source.id, team_id=self.team.id, url="https://docs.example.com/new")

        source.refresh_from_db()
        assert source.source_url == "https://docs.example.com/old"

    def test_a_name_only_edit_still_works_at_the_limit(self) -> None:
        source = KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="Docs",
            source_type=SourceType.URL,
            source_url="https://docs.example.com/old",
            status=SourceStatus.READY,
        )

        with patch(INGESTION_LIMITED, return_value=True):
            logic.update_url_source(source_id=source.id, team_id=self.team.id, name="Renamed docs")

        source.refresh_from_db()
        assert source.name == "Renamed docs"


class TestUsageAggregation(_BillingTest):
    @time_machine.travel("2026-10-15T12:00:00Z", tick=False)
    def test_usage_is_summed_per_team_inside_the_window(self) -> None:
        now = timezone.now()
        for quantity in (3, 4):
            billing.record_chunks_ingested(
                team_id=self.team.id, quantity=quantity, surface="text", source_id=None, document_id=None
            )
        billing.record_query(team_id=self.team.id, trace_id="trace-1", surface="api")
        billing.record_query(team_id=self.team.id, trace_id="trace-old", surface="api")
        KnowledgeUsageRecord.objects.unscoped().filter(idempotency_key="trace-old").update(
            created_at=now - timedelta(days=40)
        )

        begin, end = now - timedelta(days=1), now + timedelta(days=1)
        assert billing.get_chunks_by_team(begin, end) == [(self.team.id, 7)]
        assert billing.get_queries_by_team(begin, end) == [(self.team.id, 1)]
        assert billing.get_team_usage(self.team.id, begin, end) == billing.KnowledgeUsage(chunks=7, queries=1)

    def test_zero_chunks_write_no_row(self) -> None:
        billing.record_chunks_ingested(
            team_id=self.team.id, quantity=0, surface="text", source_id=None, document_id=None
        )

        assert self._rows(KnowledgeUsageKey.CHUNKS) == []


class TestQuota(_BillingTest):
    @parameterized.expand([("ingestion", quota.is_ingestion_limited), ("retrieval", quota.is_retrieval_limited)])
    def test_a_failed_quota_lookup_lets_the_work_through(self, _name, check) -> None:
        with patch("ee.billing.quota_limiting.is_team_limited", side_effect=RuntimeError("redis down")):
            assert check(self.team.id) is False

    @parameterized.expand(
        [
            ("ingestion", quota.is_ingestion_limited, "business_knowledge_chunks"),
            ("retrieval", quota.is_retrieval_limited, "business_knowledge_queries"),
        ]
    )
    def test_checks_the_matching_quota_resource(self, _name, check, resource) -> None:
        with patch("ee.billing.quota_limiting.is_team_limited", return_value=True) as is_team_limited:
            assert check(self.team.id) is True

        assert is_team_limited.call_args.args[0] == self.team.api_token
        assert is_team_limited.call_args.args[1].value == resource


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestUsageAPI(_BillingTest):
    def test_usage_reports_this_period(self, _ff) -> None:
        billing.record_chunks_ingested(
            team_id=self.team.id, quantity=5, surface="text", source_id=None, document_id=None
        )
        billing.record_query(team_id=self.team.id, trace_id="trace-1", surface="api")

        with patch(INGESTION_LIMITED, return_value=True), patch(RETRIEVAL_LIMITED, return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/business_knowledge/sources/usage/")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["chunks"] == {
            "used": 5,
            "organization_used": None,
            "free_allowance": billing.FREE_CHUNKS_PER_MONTH,
            "billing_limit": None,
            "limited": True,
        }
        assert body["queries"]["used"] == 1
        assert body["queries"]["limited"] is False

    def test_usage_treats_an_empty_billing_summary_as_unsynced(self, _ff) -> None:
        # A billing sync that omits these meters stores `{}`, which must not read as zero organization usage.
        self.organization.usage = {"business_knowledge_chunks": {}, "business_knowledge_queries": {}}
        self.organization.save(update_fields=["usage"])
        billing.record_chunks_ingested(
            team_id=self.team.id, quantity=5, surface="text", source_id=None, document_id=None
        )

        with patch(INGESTION_LIMITED, return_value=False), patch(RETRIEVAL_LIMITED, return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/business_knowledge/sources/usage/")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["chunks"]["used"] == 5
        assert body["chunks"]["organization_used"] is None
        assert body["queries"]["organization_used"] is None

    def test_search_returns_403_when_the_query_limit_is_reached(self, _ff) -> None:
        with patch(RETRIEVAL_LIMITED, return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/business_knowledge/documents/search/", {"query": "refunds"}
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.json()["detail"] == logic.RETRIEVAL_LIMITED_MESSAGE
