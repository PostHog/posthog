from __future__ import annotations

from django.db import models

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_signing_secret"

    def __str__(self) -> str:
        return f"SigningSecret(team={self.team_id})"
