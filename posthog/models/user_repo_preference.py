from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDModel


class UserRepoPreference(UUIDModel):
    class ScopeType(models.TextChoices):
        SLACK_CHANNEL = "slack_channel"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="user_repo_preferences")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_repo_preferences")
    scope_type = models.CharField(max_length=32, choices=ScopeType)
    scope_id = models.CharField(max_length=128, default="", blank=True)
    repository = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "user", "scope_type"], name="idx_user_repo_pref_lookup"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "scope_type", "scope_id"],
                name="uniq_user_repo_preference",
            )
        ]

    @classmethod
    def _validate_scope_type(cls, scope_type: "ScopeType | str") -> str:
        valid = {choice.value for choice in cls.ScopeType}
        value = scope_type.value if isinstance(scope_type, cls.ScopeType) else scope_type
        if value not in valid:
            raise ValueError(f"Invalid scope_type {value!r}, expected one of {valid}")
        return value

    @classmethod
    def get_default(cls, team_id: int, user_id: int, scope_type: "ScopeType | str", scope_id: str = "") -> str | None:
        st = cls._validate_scope_type(scope_type)
        pref = cls.objects.filter(
            team_id=team_id,
            user_id=user_id,
            scope_type=st,
            scope_id=scope_id or "",
        ).first()
        return pref.repository if pref else None

    @classmethod
    def set_default(
        cls, team_id: int, user_id: int, scope_type: "ScopeType | str", scope_id: str = "", *, repository: str
    ) -> None:
        st = cls._validate_scope_type(scope_type)
        cls.objects.update_or_create(
            team_id=team_id,
            user_id=user_id,
            scope_type=st,
            scope_id=scope_id or "",
            defaults={"repository": repository},
        )

    @classmethod
    def clear_default(cls, team_id: int, user_id: int, scope_type: "ScopeType | str", scope_id: str = "") -> bool:
        st = cls._validate_scope_type(scope_type)
        count, _ = cls.objects.filter(
            team_id=team_id,
            user_id=user_id,
            scope_type=st,
            scope_id=scope_id or "",
        ).delete()
        return bool(count)
