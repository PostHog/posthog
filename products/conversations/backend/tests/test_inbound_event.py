from datetime import datetime

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    InboundPayloadTooLargeError,
)
from products.conversations.backend.models.inbound_event import INBOUND_ERROR_MAX_LENGTH, INBOUND_PAYLOAD_MAX_BYTES


class TestConversationInboundEvent(BaseTest):
    def _create(
        self,
        *,
        team: Team | None = None,
        source: str = ConversationInboundEventSource.SLACK_EVENTS,
        source_id: str = "Ev00000001",
        provider_account_id: str = "T00000001",
        status: str = ConversationInboundEvent.Status.PENDING,
        payload: dict[str, str] | None = None,
        last_error: str = "",
        terminal_at: datetime | None = None,
    ) -> ConversationInboundEvent:
        team = team or self.team
        return ConversationInboundEvent.objects.for_team(team.id).create(
            team=team,
            source=source,
            source_id=source_id,
            provider_account_id=provider_account_id,
            status=status,
            payload=payload,
            last_error=last_error,
            terminal_at=terminal_at,
        )

    def test_queryset_without_team_context_raises(self) -> None:
        # Bare objects.all() must not return every team's receipts.
        self._create()
        with self.assertRaises(TeamScopeError):
            list(ConversationInboundEvent.objects.all())

    def test_for_team_excludes_other_teams_rows(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        mine = self._create(source_id="Ev-mine")
        self._create(team=other_team, source_id="Ev-other")

        results = list(ConversationInboundEvent.objects.for_team(self.team.id))
        self.assertEqual(results, [mine])

    def test_duplicate_source_id_for_same_team_and_source_rejected(self) -> None:
        # Slack retries reuse event_id; without this unique key they would double-process.
        self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create()

    def test_child_environment_keeps_provider_identity_under_canonical_team(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        row = self._create(team=child_team, provider_account_id="T-child")

        self.assertEqual(row.team_id, self.team.id)
        self.assertEqual(row.provider_account_id, "T-child")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(source_id=row.source_id)

    def test_empty_source_id_rejected(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(source_id="")

    def test_empty_provider_account_id_rejected(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(provider_account_id="")

    @parameterized.expand(
        [
            ("other_team", True, ConversationInboundEventSource.SLACK_EVENTS),
            ("other_source", False, ConversationInboundEventSource.SLACK_INTERACTIVITY),
        ]
    )
    def test_source_id_can_repeat_across_teams_or_sources(self, _name: str, other_team: bool, source: str) -> None:
        first = self._create()
        team = (
            Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
            if other_team
            else self.team
        )
        second = self._create(team=team, source=source)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(
            ConversationInboundEvent.objects.unscoped().filter(source_id=first.source_id).count(),
            2,
        )

    def test_oversized_payload_rejected_on_save(self) -> None:
        payload = {"text": "x" * (INBOUND_PAYLOAD_MAX_BYTES + 1)}
        with self.assertRaises(InboundPayloadTooLargeError):
            self._create(payload=payload)
        self.assertFalse(ConversationInboundEvent.objects.for_team(self.team.id).exists())

    def test_oversized_payload_rejected_on_queryset_update(self) -> None:
        row = self._create(payload={"text": "small"})
        payload = {"text": "x" * (INBOUND_PAYLOAD_MAX_BYTES + 1)}

        with self.assertRaises(IntegrityError), transaction.atomic():
            ConversationInboundEvent.objects.for_team(self.team.id).filter(id=row.id).update(payload=payload)

    def test_last_error_is_truncated_on_save(self) -> None:
        row = self._create(last_error="e" * (INBOUND_ERROR_MAX_LENGTH + 50))
        row.refresh_from_db()
        self.assertEqual(len(row.last_error), INBOUND_ERROR_MAX_LENGTH)

    def test_save_sets_terminal_timestamp(self) -> None:
        row = self._create(status=ConversationInboundEvent.Status.PROCESSED)
        self.assertIsNotNone(row.terminal_at)

    def test_queryset_update_requires_terminal_timestamp(self) -> None:
        row = self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConversationInboundEvent.objects.for_team(self.team.id).filter(id=row.id).update(
                status=ConversationInboundEvent.Status.FAILED
            )

    def test_queryset_update_requires_clearing_terminal_timestamp_on_redrive(self) -> None:
        row = self._create(status=ConversationInboundEvent.Status.FAILED)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConversationInboundEvent.objects.for_team(self.team.id).filter(id=row.id).update(
                status=ConversationInboundEvent.Status.PENDING
            )
