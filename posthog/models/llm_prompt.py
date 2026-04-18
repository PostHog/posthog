import re
import json
from typing import Any

from django.db import models, transaction
from django.db.models import Count, DateTimeField, IntegerField, OuterRef, QuerySet, Subquery, UUIDField
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from posthog.exceptions_capture import capture_exception
from posthog.models.utils import UUIDModel

# Linear-time heading parser. `[ \t]+` / `(.*)` don't overlap with each other, so no catastrophic
# backtracking. ATX closing hashes must be preceded by whitespace per CommonMark, which also
# preserves literal trailing `#` in text like `C#` or `F#`.
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_ATX_CLOSE_RE = re.compile(r"[ \t]+#+[ \t]*$")


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
    if not text:
        return []
    outline: list[dict[str, Any]] = []
    for line in text.split("\n"):
        match = _MARKDOWN_HEADING_RE.match(line.strip())
        if not match:
            continue
        heading = _ATX_CLOSE_RE.sub("", match.group(2)).rstrip()
        if heading:
            outline.append({"level": len(match.group(1)), "text": heading})
    return outline


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
