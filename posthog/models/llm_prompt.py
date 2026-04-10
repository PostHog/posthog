import json
from typing import Any

from django.db import models, transaction
from django.db.models import Count, DateTimeField, IntegerField, OuterRef, QuerySet, Subquery, UUIDField
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from posthog.exceptions_capture import capture_exception
from posthog.models.utils import UUIDModel


def normalize_prompt_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return ""


class LLMPrompt(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name", "version"],
                condition=models.Q(deleted=False),
                name="unique_llm_prompt_version_per_team",
            ),
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(deleted=False, is_latest=True),
                name="unique_llm_prompt_latest_per_team",
            ),
        ]

    name = models.CharField(max_length=255)

    # The prompt content as JSON (currently a string, may expand to array of objects)
    prompt = models.JSONField()

    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)

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


def annotate_llm_prompt_version_history_metadata(queryset: QuerySet[LLMPrompt]) -> QuerySet[LLMPrompt]:
    active_versions = LLMPrompt.objects.filter(team_id=OuterRef("team_id"), name=OuterRef("name"), deleted=False)

    version_count = Subquery(
        active_versions.values("name").annotate(count=Count("id")).values("count")[:1],
        output_field=IntegerField(),
    )
    latest_version = Subquery(
        active_versions.order_by("-version", "-created_at", "-id").values("version")[:1],
        output_field=IntegerField(),
    )
    first_version_created_at = Subquery(
        active_versions.filter(version=1).order_by("created_at", "id").values("created_at")[:1],
        output_field=DateTimeField(),
    )
    first_version_id = Subquery(
        active_versions.filter(version=1).order_by("created_at", "id").values("id")[:1],
        output_field=UUIDField(),
    )

    return queryset.annotate(
        version_count=version_count,
        latest_version=latest_version,
        first_version_created_at=first_version_created_at,
        first_version_id=first_version_id,
    )


@receiver(post_save, sender=LLMPrompt)
@receiver(post_delete, sender=LLMPrompt)
def invalidate_llm_prompt_cache(sender: type[LLMPrompt], instance: LLMPrompt, **kwargs) -> None:
    team_id = instance.team_id

    def clear_cache() -> None:
        from posthog.storage.llm_prompt_cache import invalidate_prompt_latest_cache, invalidate_prompt_version_cache

        try:
            invalidate_prompt_latest_cache(team_id, instance.name)
            invalidate_prompt_version_cache(team_id, instance.name, instance.version)
        except Exception as err:
            capture_exception(err)

    transaction.on_commit(clear_cache)
