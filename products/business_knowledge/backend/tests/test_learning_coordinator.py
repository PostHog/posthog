from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio import activity
from temporalio.client import ScheduleOverlapPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.team import Team

from products.business_knowledge.backend import learning_settings, logic
from products.business_knowledge.backend.learning import providers as providers_mod
from products.business_knowledge.backend.learning.contracts import EvidenceBundle, EvidenceRef, evidence_key_for
from products.business_knowledge.backend.learning.providers import register_learning_provider
from products.business_knowledge.backend.models import (
    KnowledgeDocument,
    KnowledgeLearningRun,
    LearningRunResult,
    LearningRunStatus,
)
from products.business_knowledge.backend.temporal.learning.activities.collect import collect_learning_evidence
from products.business_knowledge.backend.temporal.learning.constants import (
    ANALYSIS_VERSION,
    LEARNING_MAX_ITEMS_PER_TEAM,
    LEARNING_MAX_ITEMS_PER_TICK,
)
from products.business_knowledge.backend.temporal.learning.coordinator import (
    BusinessKnowledgeLearningCoordinatorWorkflow,
)
from products.business_knowledge.backend.temporal.learning.schemas import (
    AnalyzeLearningEvidenceInput,
    AnalyzeLearningEvidenceOutput,
    CollectLearningEvidenceOutput,
    LearningCoordinatorInput,
    LearningWorkItem,
)
from products.business_knowledge.backend.temporal.learning.workflow import BusinessKnowledgeLearningWorkflow
from products.business_knowledge.backend.temporal.schedule import (
    LEARNING_SCHEDULE_ID,
    create_business_knowledge_learning_coordinator_schedule,
)

COLLECT_MODULE = "products.business_knowledge.backend.temporal.learning.activities.collect"
SCHEDULE_MODULE = "products.business_knowledge.backend.temporal.schedule"


def _evidence(source_team_id: int, seed: int, *, revision_at: datetime | None = None) -> EvidenceRef:
    ticket_id = UUID(int=seed * 2 + 1)
    comment_id = UUID(int=seed * 2 + 2)
    return EvidenceRef(
        evidence_key=evidence_key_for(ticket_id, comment_id),
        source_team_id=source_team_id,
        display_label=f"ticket #{seed + 1}",
        deep_link=f"https://example.com/tickets/{seed + 1}",
        provider="conversations",
        ticket_id=ticket_id,
        ticket_number=seed + 1,
        resolution_comment_id=comment_id,
        revision_at=revision_at or datetime.now(UTC) - timedelta(minutes=10),
    )


class _Provider:
    name = "conversations"

    def __init__(self) -> None:
        self.refs_by_team: dict[int, list[EvidenceRef]] = {}
        self.calls: list[tuple[int, datetime, int, int, UUID | None]] = []

    def collect(
        self,
        team_id: int,
        *,
        since: datetime,
        limit: int,
        offset: int = 0,
        ticket_id: UUID | None = None,
    ) -> list[EvidenceRef]:
        self.calls.append((team_id, since, limit, offset, ticket_id))
        refs = self.refs_by_team.get(team_id, [])
        if ticket_id is not None:
            refs = [ref for ref in refs if ref.ticket_id == ticket_id]
        return refs[offset : offset + limit]

    def load(self, ref: EvidenceRef) -> EvidenceBundle | None:
        return None


class TestCollectLearningEvidence(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_providers = providers_mod._providers.copy()
        providers_mod._providers.clear()
        self.provider = _Provider()
        register_learning_provider(self.provider)
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"ai_suggestions_enabled": False}
        self.team.save(update_fields=["conversations_enabled", "conversations_settings"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        learning_settings.set_learn_from_support_enabled(self.team, True)
        self.provider.refs_by_team[self.team.id] = [_evidence(self.team.id, 1)]

    def tearDown(self) -> None:
        providers_mod._providers.clear()
        providers_mod._providers.update(self.saved_providers)
        super().tearDown()

    @parameterized.expand(
        [
            ("setting_off", False, True, True, True),
            ("feature_flag_off", True, False, True, True),
            ("ai_approval_off", True, True, False, True),
            ("support_off", True, True, True, False),
        ]
    )
    def test_gate_blocks_collection(
        self,
        _name: str,
        setting_enabled: bool,
        feature_flag_enabled: bool,
        ai_approved: bool,
        support_enabled: bool,
    ) -> None:
        learning_settings.set_learn_from_support_enabled(self.team, setting_enabled)
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.team.conversations_enabled = support_enabled
        self.team.save(update_fields=["conversations_enabled"])

        with patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=feature_flag_enabled):
            result = collect_learning_evidence(LearningCoordinatorInput())

        assert result.items == []

    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_conversations_ai_setting_does_not_gate_learning(self, _feature_flag) -> None:
        result = collect_learning_evidence(LearningCoordinatorInput())

        assert len(result.items) == 1
        assert result.items[0].evidence == self.provider.refs_by_team[self.team.id][0]

    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_child_environment_creates_run_on_canonical_team(self, _feature_flag) -> None:
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        child = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
            conversations_enabled=True,
        )
        self.provider.refs_by_team[self.team.id] = []
        self.provider.refs_by_team[child.id] = [_evidence(child.id, 2)]

        result = collect_learning_evidence(LearningCoordinatorInput())

        assert len(result.items) == 1
        assert result.items[0].team_id == self.team.id
        assert result.items[0].evidence.source_team_id == child.id
        run = KnowledgeLearningRun.objects.for_team(self.team.id).get(id=result.items[0].run_id)
        assert run.team_id == self.team.id
        assert run.source_team_id == child.id

    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_completed_revision_is_skipped_and_failed_revision_is_retried(self, _feature_flag) -> None:
        completed_ref = _evidence(self.team.id, 3)
        failed_ref = _evidence(self.team.id, 4)
        self.provider.refs_by_team[self.team.id] = [completed_ref, failed_ref]
        KnowledgeLearningRun.objects.for_team(self.team.id).create(
            team=self.team,
            provider=completed_ref.provider,
            evidence_key=completed_ref.evidence_key,
            source_team_id=self.team.id,
            analysis_version=ANALYSIS_VERSION,
            status=LearningRunStatus.COMPLETED,
            result=LearningRunResult.NO_KNOWLEDGE,
        )
        failed_run = KnowledgeLearningRun.objects.for_team(self.team.id).create(
            team=self.team,
            provider=failed_ref.provider,
            evidence_key=failed_ref.evidence_key,
            source_team_id=self.team.id,
            analysis_version=ANALYSIS_VERSION,
            status=LearningRunStatus.FAILED,
            error="extraction_model_failed",
        )
        KnowledgeLearningRun.objects.for_team(self.team.id).filter(id=failed_run.id).update(
            updated_at=timezone.now() - timedelta(hours=2)
        )

        result = collect_learning_evidence(LearningCoordinatorInput())
        immediate_retry = collect_learning_evidence(LearningCoordinatorInput())

        assert [item.evidence for item in result.items] == [failed_ref]
        assert result.items[0].run_id == str(failed_run.id)
        assert immediate_retry.items == []

    @patch(f"{COLLECT_MODULE}.timezone.now", return_value=datetime(2026, 9, 12, tzinfo=UTC))
    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_fresh_revision_waits_for_settle_window(self, _feature_flag, _now) -> None:
        fresh = _evidence(self.team.id, 5, revision_at=datetime(2026, 9, 11, 23, 58, tzinfo=UTC))
        settled = _evidence(self.team.id, 6, revision_at=datetime(2026, 9, 11, 23, 54, tzinfo=UTC))
        self.provider.refs_by_team[self.team.id] = [fresh, settled]

        result = collect_learning_evidence(LearningCoordinatorInput())

        assert [item.evidence for item in result.items] == [settled]

    @patch(f"{COLLECT_MODULE}.LEARNING_PROVIDER_MAX_SCAN_LIMIT", 10)
    @patch(f"{COLLECT_MODULE}.LEARNING_PROVIDER_SCAN_LIMIT", 2)
    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_completed_page_does_not_starve_older_revision(self, _feature_flag) -> None:
        completed_refs = [_evidence(self.team.id, seed) for seed in (7, 8)]
        unseen_ref = _evidence(self.team.id, 9)
        self.provider.refs_by_team[self.team.id] = [*completed_refs, unseen_ref]
        for ref in completed_refs:
            KnowledgeLearningRun.objects.for_team(self.team.id).create(
                team=self.team,
                provider=ref.provider,
                evidence_key=ref.evidence_key,
                source_team_id=self.team.id,
                analysis_version=ANALYSIS_VERSION,
                status=LearningRunStatus.COMPLETED,
                result=LearningRunResult.NO_KNOWLEDGE,
            )
        KnowledgeLearningRun.objects.for_team(self.team.id).update(created_at=timezone.now() - timedelta(days=30))

        result = collect_learning_evidence(LearningCoordinatorInput())

        assert [item.evidence for item in result.items] == [unseen_ref]
        assert [call[3] for call in self.provider.calls] == [0, 2]

    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_active_and_backed_off_runs_do_not_consume_team_cap(self, _feature_flag) -> None:
        blocked_refs = [_evidence(self.team.id, seed) for seed in range(40, 50)]
        unseen_ref = _evidence(self.team.id, 50)
        self.provider.refs_by_team[self.team.id] = [*blocked_refs, unseen_ref]
        for index, ref in enumerate(blocked_refs):
            KnowledgeLearningRun.objects.for_team(self.team.id).create(
                team=self.team,
                provider=ref.provider,
                evidence_key=ref.evidence_key,
                source_team_id=self.team.id,
                analysis_version=ANALYSIS_VERSION,
                status=LearningRunStatus.RUNNING if index % 2 == 0 else LearningRunStatus.FAILED,
            )

        result = collect_learning_evidence(LearningCoordinatorInput())

        assert [item.evidence for item in result.items] == [unseen_ref]

    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_per_team_and_global_caps_bound_each_tick(self, _feature_flag) -> None:
        teams = [self.team]
        for index in range(5):
            team = Team.objects.create_with_data(
                organization=self.organization,
                initiating_user=self.user,
                name=f"Team {index}",
            )
            team.conversations_enabled = True
            team.save(update_fields=["conversations_enabled"])
            learning_settings.set_learn_from_support_enabled(team, True)
            teams.append(team)
        for team_index, team in enumerate(teams):
            self.provider.refs_by_team[team.id] = [
                _evidence(team.id, team_index * 100 + item_index)
                for item_index in range(LEARNING_MAX_ITEMS_PER_TEAM + 1)
            ]

        result = collect_learning_evidence(LearningCoordinatorInput())

        counts = Counter(item.team_id for item in result.items)
        assert len(result.items) == LEARNING_MAX_ITEMS_PER_TICK
        assert all(count <= LEARNING_MAX_ITEMS_PER_TEAM for count in counts.values())

    @patch(f"{COLLECT_MODULE}.LEARNING_MAX_ITEMS_PER_TICK", 1)
    @patch(f"{COLLECT_MODULE}.LEARNING_MAX_ITEMS_PER_TEAM", 1)
    @patch(f"{COLLECT_MODULE}.timezone.now")
    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_tick_rotates_first_team_before_global_cap(self, _feature_flag, now_mock) -> None:
        first_tick = datetime.now(UTC).replace(second=0, microsecond=0)
        now_mock.return_value = first_tick
        other_team = Team.objects.create_with_data(
            organization=self.organization,
            initiating_user=self.user,
            name="Other team",
        )
        other_team.conversations_enabled = True
        other_team.save(update_fields=["conversations_enabled"])
        learning_settings.set_learn_from_support_enabled(other_team, True)
        revision_at = first_tick - timedelta(minutes=10)
        self.provider.refs_by_team[self.team.id] = [
            _evidence(self.team.id, 60, revision_at=revision_at),
            _evidence(self.team.id, 61, revision_at=revision_at),
        ]
        self.provider.refs_by_team[other_team.id] = [
            _evidence(other_team.id, 62, revision_at=revision_at),
            _evidence(other_team.id, 63, revision_at=revision_at),
        ]

        first_result = collect_learning_evidence(LearningCoordinatorInput())
        now_mock.return_value = first_tick + timedelta(minutes=5)
        second_result = collect_learning_evidence(LearningCoordinatorInput())

        assert {first_result.items[0].team_id, second_result.items[0].team_id} == {
            self.team.id,
            other_team.id,
        }

    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_duplicate_evidence_across_children_creates_one_run(self, _feature_flag) -> None:
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        children = [
            Team.objects.create(
                organization=self.organization,
                project=self.project,
                parent_team=self.team,
                name=f"Child {index}",
                conversations_enabled=True,
            )
            for index in range(2)
        ]
        first_ref = _evidence(children[0].id, 20)
        second_ref = EvidenceRef(
            evidence_key=first_ref.evidence_key,
            source_team_id=children[1].id,
            display_label=first_ref.display_label,
            deep_link=first_ref.deep_link,
            provider=first_ref.provider,
            ticket_id=first_ref.ticket_id,
            ticket_number=first_ref.ticket_number,
            resolution_comment_id=first_ref.resolution_comment_id,
            revision_at=first_ref.revision_at,
        )
        self.provider.refs_by_team[children[0].id] = [first_ref]
        self.provider.refs_by_team[children[1].id] = [second_ref]

        result = collect_learning_evidence(LearningCoordinatorInput())

        assert len(result.items) == 1
        assert KnowledgeLearningRun.objects.for_team(self.team.id).count() == 1

    @patch(f"{COLLECT_MODULE}.timezone.now", return_value=datetime(2026, 9, 12, tzinfo=UTC))
    @patch(f"{COLLECT_MODULE}.LEARNING_PROVIDER_SCAN_LIMIT", 1)
    @patch(f"{COLLECT_MODULE}.logic.has_feature_flag", return_value=True)
    def test_manual_input_targets_one_ticket_before_pagination(self, _feature_flag, _now) -> None:
        revision_at = datetime(2026, 8, 1, tzinfo=UTC)
        selected = _evidence(self.team.id, 30, revision_at=revision_at)
        self.provider.refs_by_team[self.team.id] = [
            _evidence(self.team.id, 31, revision_at=revision_at),
            selected,
        ]

        result = collect_learning_evidence(
            LearningCoordinatorInput(
                team_id=self.team.id,
                ticket_id=str(selected.ticket_id),
                lookback_days=30,
            )
        )

        assert [item.evidence for item in result.items] == [selected]
        assert self.provider.calls[0][1] == datetime(2026, 8, 13, tzinfo=UTC)
        assert self.provider.calls[0][4] == selected.ticket_id


@pytest.mark.asyncio
async def test_learning_schedule_does_not_trigger_during_registration() -> None:
    client = AsyncMock()
    with (
        patch(f"{SCHEDULE_MODULE}.a_schedule_exists", new=AsyncMock(return_value=False)),
        patch(f"{SCHEDULE_MODULE}.a_create_schedule", new=AsyncMock()) as create_schedule,
    ):
        await create_business_knowledge_learning_coordinator_schedule(client)

    await_args = create_schedule.await_args
    assert await_args is not None
    schedule = await_args.args[2]
    assert await_args.args[:2] == (client, LEARNING_SCHEDULE_ID)
    assert await_args.kwargs["trigger_immediately"] is False
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_worker_orchestrates_child_and_publishes_generated_document(team: Team) -> None:
    evidence = _evidence(team.id, 40)
    item = LearningWorkItem(team_id=team.id, run_id=str(uuid4()), evidence=evidence)

    @activity.defn(name="collect_learning_evidence_activity")
    async def collect_activity(_input: LearningCoordinatorInput) -> CollectLearningEvidenceOutput:
        return CollectLearningEvidenceOutput(items=[item, item])

    @activity.defn(name="analyze_learning_evidence_activity")
    async def analyze_activity(_input: AnalyzeLearningEvidenceInput) -> AnalyzeLearningEvidenceOutput:
        published = await sync_to_async(logic.create_generated_knowledge_document)(
            logic.CreateGeneratedKnowledgeDocument(
                team_id=team.id,
                provider=evidence.provider,
                ticket_id=evidence.ticket_id,
                ticket_number=evidence.ticket_number,
                source_team_id=evidence.source_team_id,
                resolution_comment_id=evidence.resolution_comment_id,
                analysis_version=ANALYSIS_VERSION,
                title="Refund policy",
                content="Refunds are available within 30 days.",
            )
        )
        return AnalyzeLearningEvidenceOutput(
            result="knowledge_created",
            knowledge_document_id=str(published.id),
            rejection_code="none",
        )

    child_id = BusinessKnowledgeLearningWorkflow.workflow_id_for(item)
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="business-knowledge-learning-test",
            workflows=[BusinessKnowledgeLearningCoordinatorWorkflow, BusinessKnowledgeLearningWorkflow],
            activities=[collect_activity, analyze_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            coordinator_result = await environment.client.execute_workflow(
                BusinessKnowledgeLearningCoordinatorWorkflow.run,
                LearningCoordinatorInput(),
                id="business-knowledge-learning-test-coordinator",
                task_queue="business-knowledge-learning-test",
            )
            child_result = await environment.client.get_workflow_handle(child_id).result()

    document_exists = await sync_to_async(
        lambda: KnowledgeDocument.objects.for_team(team.id).filter(id=child_result["knowledge_document_id"]).exists()
    )()
    assert coordinator_result.eligible_count == 2
    assert coordinator_result.started_count == 1
    assert coordinator_result.skipped_count == 1
    assert child_result["result"] == "knowledge_created"
    assert document_exists is True
