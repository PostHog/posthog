from __future__ import annotations

from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.utils import UUIDModel


class SigningSecret(UUIDModel):
    """Per-team secret for widget identity verification (HMAC signing).

    Replaces the legacy plaintext Team.secret_api_token for Conversations (#63111).
    HMAC verification needs the raw value server-side, so the secret is encrypted at
    rest rather than hashed — and it is only ever valid for signing, never for API
    authentication, so a leaked value can't call any API.

    Environment-scoped on purpose: sibling environments hold independent secrets,
    mirroring Team.secret_api_token. No RootTeamMixin (its save() canonicalizes team
    to the parent), and `EnvironmentScopedManager` filters by the literal team id —
    readers pass the environment's own id via `objects.for_team(team.id)`.
    """

    # How long the previous secret keeps verifying after a rotation. Customers sign
    # hashes on their servers, so they need a deploy window to pick up the new value.
    PREVIOUS_SECRET_GRACE = timedelta(hours=48)

    objects = EnvironmentScopedManager()

    # db_constraint=False so CreateModel takes no lock on posthog_team.
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="conversations_signing_secret",
    )
    # Encryption/decryption is transparent via the field; value reads back as the raw string.
    # Non-deterministic ciphertext: never filter by this value — fetch by team and compare.
    secret = EncryptedTextField()
    # Set on rotation via the conversations endpoint: the secret stops mirroring the legacy token.
    rotated_independently = models.BooleanField(default=False)
    # The secret that `secret` replaced, kept verifying for PREVIOUS_SECRET_GRACE after
    # previous_secret_rotated_at so in-flight hashes survive a rotation. Expiry is judged
    # at read time; the next rotation supersedes the value, and the revocation paths
    # (expire_previous, the rotation and backup-deletion receivers) clear it.
    previous_secret = EncryptedTextField(null=True)
    previous_secret_rotated_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_signing_secret"

    def __str__(self) -> str:
        return f"SigningSecret(team={self.team_id})"

    @property
    def previous_secret_valid_until(self) -> datetime | None:
        if not self.previous_secret or not self.previous_secret_rotated_at:
            return None
        return self.previous_secret_rotated_at + self.PREVIOUS_SECRET_GRACE

    @property
    def previous_secret_active(self) -> bool:
        valid_until = self.previous_secret_valid_until
        return valid_until is not None and timezone.now() < valid_until
