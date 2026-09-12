from datetime import datetime
from io import StringIO
from uuid import UUID

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.business_knowledge.backend.learning import providers as providers_mod
from products.business_knowledge.backend.learning.contracts import EvidenceBundle, EvidenceRef, evidence_key_for
from products.business_knowledge.backend.learning.providers import (
    get_learning_provider,
    get_learning_providers,
    register_learning_provider,
)
from products.business_knowledge.backend.models import KnowledgeLearningRun, LearningProvider

LEARNING_RUN_MIGRATION = "0018_knowledge_learning_run"
_TICKET_ID = UUID("10000000-0000-0000-0000-000000000001")
_COMMENT_ID = UUID("20000000-0000-0000-0000-000000000002")


class _FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def collect(self, team_id: int, *, since: datetime, limit: int) -> list[EvidenceRef]:
        return []

    def load(self, ref: EvidenceRef) -> EvidenceBundle | None:
        return None


class TestLearningProviders(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._saved = providers_mod._providers.copy()
        providers_mod._providers.clear()

    def tearDown(self) -> None:
        providers_mod._providers.clear()
        providers_mod._providers.update(self._saved)
        super().tearDown()

    def test_register_then_get_returns_the_provider(self) -> None:
        provider = _FakeProvider("conversations")
        register_learning_provider(provider)

        assert get_learning_providers() == [provider]
        assert get_learning_provider("conversations") is provider

    def test_duplicate_name_is_rejected(self) -> None:
        # Two products registering as "conversations" would silently pick one.
        register_learning_provider(_FakeProvider("conversations"))
        with self.assertRaises(ValueError) as raised:
            register_learning_provider(_FakeProvider("conversations"))

        assert "conversations" in str(raised.exception)
        assert len(get_learning_providers()) == 1

    @parameterized.expand(
        [
            ("empty", ""),
            ("uppercase", "Conversations"),
            ("too_long", "a" * 65),
        ]
    )
    def test_invalid_provider_name_is_rejected(self, _name: str, provider_name: str) -> None:
        # Publish rejects names that are not [a-z0-9_-]{1,64}; fail here instead of at write time.
        with self.assertRaises(ValueError):
            register_learning_provider(_FakeProvider(provider_name))

        assert get_learning_providers() == []


class TestEvidenceRef(SimpleTestCase):
    def _kwargs(self, **overrides: object) -> dict:
        kwargs: dict = {
            "evidence_key": evidence_key_for(_TICKET_ID, _COMMENT_ID),
            "source_team_id": 1,
            "display_label": "ticket #42",
            "deep_link": "https://example.com/ticket/42",
            "provider": "conversations",
            "ticket_id": _TICKET_ID,
            "ticket_number": 42,
            "resolution_comment_id": _COMMENT_ID,
        }
        kwargs.update(overrides)
        return kwargs

    def test_valid_ref_uses_ticket_and_comment_as_evidence_key(self) -> None:
        ref = EvidenceRef(**self._kwargs())
        assert ref.evidence_key == f"{_TICKET_ID}:{_COMMENT_ID}"

    @parameterized.expand(
        [
            ("mismatched_key", {"evidence_key": "not-the-revision"}),
            ("uppercase_provider", {"provider": "Conversations"}),
            ("zero_source_team", {"source_team_id": 0}),
            ("zero_ticket_number", {"ticket_number": 0}),
        ]
    )
    def test_invalid_ref_is_rejected(self, _name: str, overrides: dict) -> None:
        # A drifted evidence_key would unique-index a different revision than the document identity.
        with self.assertRaises(ValueError):
            EvidenceRef(**self._kwargs(**overrides))


class TestKnowledgeLearningRun(BaseTest):
    def _create(
        self,
        *,
        team: Team | None = None,
        evidence_key: str = "ticket:comment",
        analysis_version: str = "post_resolution_v1",
        source_team_id: int | None = None,
        **kwargs,
    ) -> KnowledgeLearningRun:
        team = team or self.team
        return KnowledgeLearningRun.objects.for_team(team.id).create(
            team=team,
            provider=LearningProvider.CONVERSATIONS,
            evidence_key=evidence_key,
            source_team_id=source_team_id if source_team_id is not None else team.id,
            analysis_version=analysis_version,
            **kwargs,
        )

    def test_queryset_without_team_context_raises(self) -> None:
        # Bare objects.all() must not return every team's learning runs.
        self._create()
        with self.assertRaises(TeamScopeError):
            list(KnowledgeLearningRun.objects.all())

    def test_for_team_excludes_other_teams_rows(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        mine = self._create(evidence_key="mine")
        self._create(team=other_team, evidence_key="mine")

        results = list(KnowledgeLearningRun.objects.for_team(self.team.id))
        self.assertEqual(results, [mine])

    def test_duplicate_evidence_for_same_team_provider_and_version_rejected(self) -> None:
        # Coordinator retries the same resolved-thread revision; without this they re-analyze forever.
        self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create()

    @parameterized.expand(
        [
            ("later_human_reply", {"evidence_key": "ticket:later-comment"}),
            ("new_analysis_version", {"analysis_version": "post_resolution_v2"}),
        ]
    )
    def test_new_revision_or_version_is_a_separate_run(self, _name: str, kwargs: dict) -> None:
        self._create()
        self._create(**kwargs)
        assert KnowledgeLearningRun.objects.for_team(self.team.id).count() == 2

    def test_same_evidence_allowed_across_teams(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        self._create()
        self._create(team=other_team)
        assert KnowledgeLearningRun.objects.for_team(self.team.id).count() == 1
        assert KnowledgeLearningRun.objects.for_team(other_team.id).count() == 1

    def test_child_environment_stores_canonical_team_and_keeps_source_team_id(self) -> None:
        child = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        rewritten = self._create(team=child, evidence_key="child:comment")
        explicit = self._create(evidence_key="canonical:comment", source_team_id=child.id)

        assert rewritten.team_id == self.team.id
        assert rewritten.source_team_id == child.id
        assert explicit.team_id == self.team.id
        assert explicit.source_team_id == child.id
        assert KnowledgeLearningRun.objects.for_team(self.team.id).get(pk=rewritten.pk).source_team_id == child.id

    def test_migration_sql_creates_table_without_team_fk(self) -> None:
        # A real FK here takes SHARE ROW EXCLUSIVE on posthog_team during migrate.
        out = StringIO()
        call_command("sqlmigrate", "business_knowledge", LEARNING_RUN_MIGRATION, stdout=out)
        sql = out.getvalue()

        assert "CREATE TABLE" in sql
        assert "bk_learn_run_unique" in sql
        assert "bk_learn_run_team_status" in sql
        assert "REFERENCES" not in sql
        assert "posthog_team" not in sql
