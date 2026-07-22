import json
from typing import Any

from django.db import models, transaction
from django.db.models import Count, DateTimeField, IntegerField, OuterRef, QuerySet, Subquery, UUIDField
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel

from products.ai_observability.backend.markdown_outline import get_markdown_outline


def normalize_prompt_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return ""


def get_prompt_outline(value: Any) -> list[dict[str, Any]]:
    """Extract a flat list of markdown headings from a prompt payload.

    Agents consuming the MCP/API can use this as a lightweight table of contents
    without pulling the full prompt content. Returns `[]` for non-markdown
    payloads (e.g. message arrays serialized to JSON).
    """
    text = normalize_prompt_to_string(value)
    return get_markdown_outline(text)


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
        db_table = "posthog_llmprompt"

    name = models.CharField(max_length=255)

    # The prompt content as JSON (currently a string, may expand to array of objects)
    prompt = models.JSONField()

    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)

    # Optional "what changed" note set when the version is published; immutable like the rest of the row
    version_description = models.CharField(max_length=400, null=True, blank=True)

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


class LLMPromptLabel(ModelActivityMixin, UUIDModel):
    """A movable pointer from a name (e.g. "production") to exactly one version of a prompt.

    Version rows are immutable; releasing a version means pointing a label at it and
    rolling back means pointing it back. The (team, prompt_name, name) uniqueness is
    what keeps fetch-by-label single-valued.

    Deliberately not on TeamScopedRootMixin: LLMPrompt stores raw (possibly child-env)
    team ids, and the mixin's canonical-team rewrite would put labels in a different
    team-space than the prompt rows they point into. Migrate to fail-closed scoping
    together with LLMPrompt.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "prompt_name", "name"],
                name="unique_llm_prompt_label_per_prompt",
            ),
        ]
        db_table = "posthog_llmpromptlabel"

    activity_logging_on_delete = True

    name = models.CharField(max_length=128)
    # Prompts have no parent entity — version rows are grouped by name, so the label
    # keys the prompt family by name and points at one version row via the FK below.
    prompt_name = models.CharField(max_length=255)
    prompt = models.ForeignKey(LLMPrompt, on_delete=models.CASCADE, related_name="labels")

    # db_constraint=False: posthog_team / posthog_user are hot tables — adding a real FK
    # constraint locks the parent table during migration.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


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


@receiver(post_save, sender=LLMPromptLabel)
@receiver(post_delete, sender=LLMPromptLabel)
def invalidate_llm_prompt_label_cache(sender: type[LLMPromptLabel], instance: LLMPromptLabel, **kwargs) -> None:
    # Label pointer changes never touch LLMPrompt rows, so the receiver above can't cover
    # them — without this, a moved label would keep serving the old version from cache.
    # post_save covers create (clears a cached 404 miss) and move; post_delete covers
    # removal, including archive's queryset delete.
    team_id = instance.team_id
    prompt_name = instance.prompt_name
    label_name = instance.name

    def clear_cache() -> None:
        from posthog.storage.llm_prompt_cache import invalidate_prompt_label_cache

        try:
            invalidate_prompt_label_cache(team_id, prompt_name, label_name)
        except Exception as err:
            capture_exception(err)

    transaction.on_commit(clear_cache)
