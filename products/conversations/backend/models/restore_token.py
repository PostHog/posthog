import uuid
import hashlib
import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone


def generate_restore_token() -> str:
    """Generate a cryptographically secure restore token (32 bytes, base64url encoded)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token using SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


# Default TTL for restore tokens (60 minutes)
DEFAULT_TOKEN_TTL_MINUTES = 60


class ConversationRestoreToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="conversation_restore_tokens")

    # Email to find tickets for (stored directly since we send emails to this address anyway)
    recipient_email = models.EmailField(max_length=254)

    # Lifecycle
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by_widget_session_id = models.CharField(max_length=64, null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_restore_token"
        indexes = [
            models.Index(fields=["team", "recipient_email"], name="posthog_crt_team_email_idx"),
            models.Index(fields=["expires_at"], name="posthog_crt_expires_idx"),
        ]

    def __str__(self) -> str:
        status = "consumed" if self.consumed_at else ("expired" if self.is_expired else "active")
        return f"RestoreToken {self.id} ({status})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @classmethod
    def create_token(
        cls,
        team,
        recipient_email: str,
        ttl_minutes: int = DEFAULT_TOKEN_TTL_MINUTES,
    ) -> tuple["ConversationRestoreToken", str]:
        """
        Create a new restore token.

        Returns tuple of (token_record, raw_token).
        The raw_token should be sent to the user; it's not stored.
        """
        raw_token = generate_restore_token()
        token_hash_value = hash_token(raw_token)

        token_record = cls.objects.create(
            token_hash=token_hash_value,
            team=team,
            recipient_email=recipient_email.lower().strip(),
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )

        return token_record, raw_token
