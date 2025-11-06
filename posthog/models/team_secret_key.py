import re
import secrets
from typing import TYPE_CHECKING, Optional

from django.db import models

from posthog.models.utils import int_to_base, mask_key_value

if TYPE_CHECKING:
    from posthog.models import Team, User


def generate_secret_key_id(name: str) -> str:
    """
    Generate a short secret key ID with format: phsk_{name_prefix}_{random}

    Args:
        name: The name of the secret key

    Returns:
        A secret key ID string like "phsk_mykey_a1b2c3"
    """
    # Extract first 5 alphanumeric characters from the name
    alphanumeric_only = re.sub(r"[^a-zA-Z0-9]", "", name.lower())
    name_prefix = alphanumeric_only[:5] if alphanumeric_only else "key"

    # Generate short random part (6 characters)
    random_part = int_to_base(secrets.randbits(6 * 8), 62)[:6]

    return f"phsk_{name_prefix}_{random_part}"


def generate_team_secret_key(name: str) -> str:
    """
    Generate a team secret key with format: phs_{name_prefix}_{random}

    Args:
        name: The name of the secret key

    Returns:
        A secret key string like "phs_mykey_1a2b3c4d5e..."
    """
    # Extract first 5 alphanumeric characters from the name
    alphanumeric_only = re.sub(r"[^a-zA-Z0-9]", "", name.lower())
    name_prefix = alphanumeric_only[:5] if alphanumeric_only else "key"

    # Generate random part (35 bytes like other secret tokens)
    random_part = int_to_base(secrets.randbits(35 * 8), 62)

    return f"phs_{name_prefix}_{random_part}"


class TeamSecretKey(models.Model):
    """
    A secret key for server-side operations, scoped to a team.
    Teams can have multiple secret keys for different purposes.
    """

    # Use the generated secret key ID as the primary key (e.g., "phsk_mykey_a1b2c3")
    id = models.CharField(
        max_length=50,
        primary_key=True,
        editable=False,
        help_text="Short identifier for the secret key",
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="secret_keys")
    name = models.CharField(max_length=100, help_text="Descriptive name for this secret key")

    # Masked value for display (e.g., "phs_...abcd")
    mask_value = models.CharField(max_length=20, editable=False)

    # Plaintext value for JWT verification (relies on database encryption at rest)
    secure_value = models.CharField(
        unique=True,
        max_length=300,
        editable=False,
        db_index=True,
        help_text="Secret key value for JWT verification",
    )

    last_used_at = models.DateTimeField(null=True, blank=True, help_text="When this key was last used")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_team_secret_keys",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_team_secret_key_name",
            )
        ]
        indexes = [
            models.Index(fields=["team", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.mask_value})"

    @classmethod
    def create_key(cls, team: "Team", name: str, created_by: Optional["User"] = None) -> tuple["TeamSecretKey", str]:
        """
        Create a new secret key for a team.

        Returns:
            A tuple of (TeamSecretKey instance, plaintext key value)
            The plaintext key is only returned once and should be shown to the user immediately.
        """
        # Generate the secret key ID (used as primary key)
        key_id = generate_secret_key_id(name)

        # Generate the plaintext key
        plaintext_key = generate_team_secret_key(name)

        # Create the masked version for display
        masked = mask_key_value(plaintext_key)

        # Create the model instance (storing plaintext for JWT verification)
        secret_key = cls.objects.create(
            id=key_id,
            team=team,
            name=name,
            mask_value=masked,
            secure_value=plaintext_key,
            created_by=created_by,
        )

        return secret_key, plaintext_key

    @classmethod
    def find_team_secret_key(cls, key_value: str) -> Optional["TeamSecretKey"]:
        """
        Find a team secret key by its plaintext value.

        Args:
            key_value: The plaintext secret key value

        Returns:
            The TeamSecretKey instance if found, None otherwise
        """
        try:
            return cls.objects.select_related("team").get(secure_value=key_value)
        except cls.DoesNotExist:
            return None

    def mark_used(self) -> None:
        """Update the last_used_at timestamp."""
        from django.utils import timezone

        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])
