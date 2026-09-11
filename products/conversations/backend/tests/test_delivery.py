from datetime import datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.conversations.backend.models import (
    ConversationDelivery,
    ConversationDeliveryChannel,
    ConversationDeliveryPart,
    DeliverySnapshotTooLargeError,
)
from products.conversations.backend.models.delivery import DELIVERY_ERROR_MAX_LENGTH, DELIVERY_SNAPSHOT_MAX_BYTES


class _DeliveryQueueRowTests:
    model: type[ConversationDelivery] | type[ConversationDeliveryPart]

    def _create(self, **kwargs: object):
        raise NotImplementedError

    def test_queryset_without_team_context_raises(self) -> None:
        # Bare objects.all() must not return every team's rows.
        self._create()
        with self.assertRaises(TeamScopeError):
            list(self.model.objects.all())

    def test_for_team_excludes_other_teams_rows(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        mine = self._create()
        self._create(team=other_team)

        results = list(self.model.objects.for_team(self.team.id))
        self.assertEqual(results, [mine])

    def test_last_error_is_truncated_on_save(self) -> None:
        row = self._create(last_error="e" * (DELIVERY_ERROR_MAX_LENGTH + 50))
        row.refresh_from_db()
        self.assertEqual(len(row.last_error), DELIVERY_ERROR_MAX_LENGTH)

    def test_save_sets_terminal_timestamp(self) -> None:
        row = self._create(status=self.model.Status.ACCEPTED)
        self.assertIsNotNone(row.terminal_at)

    @parameterized.expand(
        [
            ("accepted", ConversationDelivery.Status.ACCEPTED),
            ("delivered", ConversationDelivery.Status.DELIVERED),
            ("failed", ConversationDelivery.Status.FAILED),
        ]
    )
    def test_queryset_update_requires_terminal_timestamp(self, _name: str, status: str) -> None:
        row = self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.model.objects.for_team(self.team.id).filter(id=row.id).update(status=status)

    def test_queryset_update_requires_clearing_terminal_timestamp_on_redrive(self) -> None:
        row = self._create(status=self.model.Status.FAILED)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.model.objects.for_team(self.team.id).filter(id=row.id).update(status=self.model.Status.PENDING)

    @parameterized.expand([("payload",), ("route",)])
    def test_oversized_snapshot_rejected_on_save(self, field: str) -> None:
        snapshot = {"text": "x" * (DELIVERY_SNAPSHOT_MAX_BYTES + 1)}
        with self.assertRaises(DeliverySnapshotTooLargeError):
            self._create(**{field: snapshot})
        self.assertFalse(self.model.objects.for_team(self.team.id).exists())

    @parameterized.expand([("payload",), ("route",)])
    def test_oversized_snapshot_rejected_on_queryset_update(self, field: str) -> None:
        row = self._create(**{field: {"text": "small"}})
        snapshot = {"text": "x" * (DELIVERY_SNAPSHOT_MAX_BYTES + 1)}

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.model.objects.for_team(self.team.id).filter(id=row.id).update(**{field: snapshot})

    def test_conditional_update_honors_fencing_token(self) -> None:
        # A reclaimed row must ignore the stale worker's complete.
        row = self._create(status=self.model.Status.PROCESSING, fencing_token=7)
        now = timezone.now()

        stale = (
            self.model.objects.for_team(self.team.id)
            .filter(id=row.id, status=self.model.Status.PROCESSING, fencing_token=6)
            .update(status=self.model.Status.ACCEPTED, terminal_at=now)
        )
        self.assertEqual(stale, 0)
        row.refresh_from_db()
        self.assertEqual(row.status, self.model.Status.PROCESSING)
        self.assertIsNone(row.terminal_at)

        claimed = (
            self.model.objects.for_team(self.team.id)
            .filter(id=row.id, status=self.model.Status.PROCESSING, fencing_token=7)
            .update(status=self.model.Status.ACCEPTED, terminal_at=now)
        )
        self.assertEqual(claimed, 1)
        row.refresh_from_db()
        self.assertEqual(row.status, self.model.Status.ACCEPTED)
        self.assertIsNotNone(row.terminal_at)

    def test_conditional_update_requires_processing_status(self) -> None:
        row = self._create(status=self.model.Status.PENDING, fencing_token=7)
        updated = (
            self.model.objects.for_team(self.team.id)
            .filter(id=row.id, status=self.model.Status.PROCESSING, fencing_token=7)
            .update(status=self.model.Status.ACCEPTED, terminal_at=timezone.now())
        )
        self.assertEqual(updated, 0)
        row.refresh_from_db()
        self.assertEqual(row.status, self.model.Status.PENDING)

    def test_queryset_update_to_processing_requires_lease(self) -> None:
        row = self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.model.objects.for_team(self.team.id).filter(id=row.id).update(
                status=self.model.Status.PROCESSING,
            )


class TestConversationDelivery(_DeliveryQueueRowTests, BaseTest):
    model = ConversationDelivery

    def _create(
        self,
        *,
        team: Team | None = None,
        channel: str = ConversationDeliveryChannel.SLACK,
        comment_id=None,
        provider_account_id: str = "T00000001",
        status: str = ConversationDelivery.Status.PENDING,
        payload: dict[str, str] | None = None,
        route: dict[str, str] | None = None,
        last_error: str = "",
        terminal_at: datetime | None = None,
        fencing_token: int = 0,
        lease_expires_at: datetime | None = None,
    ) -> ConversationDelivery:
        team = team or self.team
        if status == ConversationDelivery.Status.PROCESSING and lease_expires_at is None:
            lease_expires_at = timezone.now() + timedelta(minutes=20)
        return ConversationDelivery.objects.for_team(team.id).create(
            team=team,
            channel=channel,
            comment_id=comment_id or uuid4(),
            provider_account_id=provider_account_id,
            status=status,
            payload=payload,
            route=route,
            last_error=last_error,
            terminal_at=terminal_at,
            fencing_token=fencing_token,
            lease_expires_at=lease_expires_at,
        )

    def test_duplicate_comment_on_same_team_and_channel_rejected(self) -> None:
        # Two Slack deliveries for one comment would double-post the body.
        first = self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(comment_id=first.comment_id)

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
            self._create(comment_id=row.comment_id)

    def test_empty_channel_rejected(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(channel="")

    def test_empty_provider_account_id_rejected(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(provider_account_id="")

    def test_comment_id_can_repeat_across_teams(self) -> None:
        first = self._create()
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        second = self._create(team=other_team, comment_id=first.comment_id)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(
            ConversationDelivery.objects.unscoped().filter(comment_id=first.comment_id).count(),
            2,
        )

    def test_same_comment_can_have_one_delivery_per_channel(self) -> None:
        first = self._create()
        second = self._create(comment_id=first.comment_id, channel="teams")
        self.assertNotEqual(first.id, second.id)


class TestConversationDeliveryPart(_DeliveryQueueRowTests, BaseTest):
    model = ConversationDeliveryPart

    def _delivery(self, *, team: Team | None = None) -> ConversationDelivery:
        team = team or self.team
        return ConversationDelivery.objects.for_team(team.id).create(
            team=team,
            channel=ConversationDeliveryChannel.SLACK,
            comment_id=uuid4(),
            provider_account_id="T00000001",
        )

    def _create(
        self,
        *,
        team: Team | None = None,
        delivery: ConversationDelivery | None = None,
        part_key: str = "body",
        status: str = ConversationDeliveryPart.Status.PENDING,
        payload: dict[str, str] | None = None,
        route: dict[str, str] | None = None,
        last_error: str = "",
        terminal_at: datetime | None = None,
        fencing_token: int = 0,
        lease_expires_at: datetime | None = None,
    ) -> ConversationDeliveryPart:
        team = team or self.team
        delivery = delivery or self._delivery(team=team)
        if status == ConversationDeliveryPart.Status.PROCESSING and lease_expires_at is None:
            lease_expires_at = timezone.now() + timedelta(minutes=20)
        return ConversationDeliveryPart.objects.for_team(team.id).create(
            team=team,
            delivery=delivery,
            part_key=part_key,
            status=status,
            payload=payload,
            route=route,
            last_error=last_error,
            terminal_at=terminal_at,
            fencing_token=fencing_token,
            lease_expires_at=lease_expires_at,
        )

    def test_duplicate_part_key_on_same_delivery_rejected(self) -> None:
        # Two body parts on one delivery would resend an accepted Slack message.
        first = self._create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(delivery=first.delivery, part_key=first.part_key)

    def test_mismatched_team_cannot_insert_a_second_body_on_the_same_delivery(self) -> None:
        first = self._create()
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(team=other_team, delivery=first.delivery, part_key=first.part_key)

    def test_same_part_key_can_repeat_across_deliveries(self) -> None:
        first = self._create(part_key="body")
        second = self._create(part_key="body")
        self.assertNotEqual(first.delivery_id, second.delivery_id)
        self.assertEqual(
            ConversationDeliveryPart.objects.unscoped().filter(part_key="body").count(),
            2,
        )

    def test_empty_part_key_rejected(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(part_key="")

    def test_child_environment_scopes_parts_to_canonical_team(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        delivery = self._delivery(team=child_team)
        row = self._create(team=child_team, delivery=delivery, part_key="body")

        self.assertEqual(delivery.team_id, self.team.id)
        self.assertEqual(row.team_id, self.team.id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(team=child_team, delivery=delivery, part_key="body")
