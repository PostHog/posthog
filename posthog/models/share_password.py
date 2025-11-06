import secrets
from typing import Optional

from django.contrib.auth.hashers import check_password, make_password
from django.db import models

from posthog.models.user import User


def generate_default_password() -> str:
    """Generate a secure random password for new share passwords."""
    return secrets.token_urlsafe(16)


class SharePassword(models.Model):
    """
    Individual password entries for sharing configurations.
    Each share can have multiple passwords with different creators and notes.
    """

    sharing_configuration = models.ForeignKey(
        "posthog.SharingConfiguration", on_delete=models.CASCADE, related_name="share_passwords"
    )

    password_hash = models.CharField(max_length=128)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, related_name="created_share_passwords"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional note for the creator to identify this password
    note = models.CharField(max_length=100, blank=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        note_part = f" ({self.note})" if self.note else ""
        creator = self.created_by.email if self.created_by else "deleted user"
        return f"Password by {creator}{note_part} - {self.created_at.strftime('%Y-%m-%d')}"

    def set_password(self, raw_password: str) -> None:
        """Hash and set the password."""
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Check if the provided password matches the stored hash."""
        return check_password(raw_password, self.password_hash)

    @classmethod
    def create_password(
        cls, sharing_configuration, created_by: User, raw_password: Optional[str] = None, note: Optional[str] = None
    ) -> tuple["SharePassword", str]:
        """
        Create a new share password entry.

        Returns:
            tuple: (SharePassword instance, raw_password)
        """
        if raw_password is None:
            raw_password = generate_default_password()

        share_password = cls(sharing_configuration=sharing_configuration, created_by=created_by, note=note or "")
        share_password.set_password(raw_password)
        share_password.save()

        return share_password, raw_password
