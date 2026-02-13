from django.db import models
from django.db.models import F
from django.utils import timezone

from posthog.models.utils import UUIDModel


class LLMPrompt(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(deleted=False),
                name="unique_llm_prompt_name_per_team",
            )
        ]

    name = models.CharField(max_length=255)
    prompt = models.JSONField()
    version = models.PositiveIntegerField(default=1)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.pk:
            update_fields = kwargs.get("update_fields")
            if update_fields is None or "prompt" in update_fields:
                try:
                    old_instance = LLMPrompt.objects.get(pk=self.pk)
                    if old_instance.prompt != self.prompt:
                        self.version = F("version") + 1
                        if update_fields is not None:
                            kwargs["update_fields"] = set(update_fields) | {"version"}
                except LLMPrompt.DoesNotExist:
                    pass
        super().save(*args, **kwargs)
