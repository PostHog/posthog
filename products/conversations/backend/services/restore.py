import uuid
import logging
from dataclasses import dataclass
from typing import Literal

from django.db import transaction
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.conversations.backend.models import ConversationRestoreToken, Ticket
from products.conversations.backend.models.restore_token import hash_token

logger = logging.getLogger(__name__)


@dataclass
class RestoreResult:
    status: Literal["success", "expired", "used", "invalid"]
    code: str | None = None
    widget_session_id: str | None = None
    migrated_ticket_ids: list[str] | None = None


class RestoreService:
    """Service for handling conversation ticket restore operations."""

    @staticmethod
    def _find_distinct_ids_by_person_email(team: Team, email_lower: str) -> list[str]:
        """
        Find distinct_ids of persons whose email matches via HogQL (ClickHouse).
        Uses the persons table's built-in pdi lazy join to person_distinct_ids.
        """
        query = parse_select(
            "SELECT DISTINCT pdi.distinct_id FROM persons WHERE lower(properties.email) = {email} LIMIT 1000",
            placeholders={"email": ast.Constant(value=email_lower)},
        )
        response = execute_hogql_query(query=query, team=team)
        return [row[0] for row in (response.results or [])]

    @staticmethod
    def find_tickets_by_email(team: Team, email: str) -> list[Ticket]:
        """
        Find all tickets associated with an email address.

        Checks both:
        1. anonymous_traits.email on Ticket (Postgres, fast)
        2. Person properties.email → distinct_id → Ticket (via HogQL/ClickHouse)
        """
        email_lower = email.lower().strip()

        person_distinct_ids: list[str] = []
        try:
            person_distinct_ids = RestoreService._find_distinct_ids_by_person_email(team, email_lower)
        except Exception:
            logger.warning(
                "Person email lookup failed during restore, falling back to anonymous_traits only",
                extra={"team_id": team.id},
            )

        tickets = Ticket.objects.filter(team=team, anonymous_traits__email__iexact=email_lower)
        if person_distinct_ids:
            tickets = tickets | Ticket.objects.filter(team=team, distinct_id__in=person_distinct_ids)
        return list(tickets.distinct())

    @staticmethod
    def invalidate_existing_tokens(
        team: Team,
        email: str,
        exclude_token_id: uuid.UUID | None = None,
    ) -> int:
        """Invalidate any unused tokens for the same email."""
        email_lower = email.lower().strip()
        now = timezone.now()

        queryset = ConversationRestoreToken.objects.filter(
            team=team,
            recipient_email=email_lower,
            consumed_at__isnull=True,
            expires_at__gt=now,
        )

        if exclude_token_id:
            queryset = queryset.exclude(id=exclude_token_id)

        # Mark as consumed (with no widget_session_id to indicate invalidation)
        updated = queryset.update(consumed_at=now)

        if updated:
            logger.info(f"Invalidated {updated} existing restore tokens for email in team {team.id}")

        return updated

    @staticmethod
    def request_restore_link(
        team: Team,
        email: str,
    ) -> str | None:
        """
        Request a restore link for a given email.

        Returns raw_token if tickets exist, None otherwise.
        The caller should send the email with the raw_token.
        """
        tickets = RestoreService.find_tickets_by_email(team, email)

        if not tickets:
            logger.info(f"No tickets found for email in team {team.id}")
            return None

        # Create new token
        token_record, raw_token = ConversationRestoreToken.create_token(
            team=team,
            recipient_email=email,
        )

        logger.info(
            f"Created restore token {token_record.id} for {len(tickets)} tickets in team {team.id}",
            extra={"token_id": str(token_record.id), "ticket_count": len(tickets)},
        )

        return raw_token

    @staticmethod
    def redeem_token(
        team: Team,
        raw_token: str,
        widget_session_id: str,
    ) -> RestoreResult:
        """
        Redeem a restore token and migrate tickets.

        The order of checks is intentional to avoid information leakage:
        1. Lookup token scoped to team (invalid if not found)
        2. Check consumed (before expiry to avoid leaking token existence)
        3. Check expired
        4. Atomically consume the token (short PG transaction)
        5. Find and migrate tickets (may hit ClickHouse, no row lock held)
        """
        token_hash_value = hash_token(raw_token)

        try:
            token = ConversationRestoreToken.objects.get(token_hash=token_hash_value, team=team)
        except ConversationRestoreToken.DoesNotExist:
            logger.warning("Invalid restore token attempted")
            return RestoreResult(status="invalid", code="token_invalid")

        if token.is_consumed:
            logger.warning(f"Restore token {token.id} already consumed")
            return RestoreResult(status="used", code="token_already_used")

        if token.is_expired:
            logger.warning(f"Restore token {token.id} expired")
            return RestoreResult(status="expired", code="token_expired")

        # Phase 1: atomically consume the token (short PG transaction, no CH calls)
        with transaction.atomic():
            token = ConversationRestoreToken.objects.select_for_update().get(id=token.id)

            if token.is_consumed:
                return RestoreResult(status="used", code="token_already_used")

            if token.is_expired:
                return RestoreResult(status="expired", code="token_expired")

            token.consumed_at = timezone.now()
            token.consumed_by_widget_session_id = widget_session_id
            token.save(update_fields=["consumed_at", "consumed_by_widget_session_id"])

        # Phase 2: find and migrate tickets (may hit ClickHouse, no row lock held).
        # Token is already consumed — if this fails the user can request a new link.
        try:
            tickets = RestoreService.find_tickets_by_email(token.team, token.recipient_email)
            migrated_ids = [t.id for t in tickets]

            if migrated_ids:
                Ticket.objects.filter(team=token.team, id__in=migrated_ids).update(widget_session_id=widget_session_id)

            RestoreService.invalidate_existing_tokens(token.team, token.recipient_email, exclude_token_id=token.id)
        except Exception:
            logger.exception(f"Failed to migrate tickets after consuming token {token.id}")
            return RestoreResult(status="success", code="migration_failed", widget_session_id=widget_session_id)

        logger.info(
            f"Restore token {token.id} redeemed, migrated {len(migrated_ids)} tickets",
            extra={"token_id": str(token.id), "migrated_count": len(migrated_ids)},
        )

        return RestoreResult(
            status="success",
            widget_session_id=widget_session_id,
            migrated_ticket_ids=[str(tid) for tid in migrated_ids],
        )
