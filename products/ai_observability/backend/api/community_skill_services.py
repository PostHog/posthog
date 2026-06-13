from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

import requests
import structlog

from posthog.models import Team, User

from ..models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillVote
from ..models.skills import LLMSkill
from .skill_serializers import validate_skill_name_value
from .skill_services import create_skill

logger = structlog.get_logger(__name__)

COMMUNITY_SKILLS_REPO = "PostHog/community-skills"
COMMUNITY_SKILLS_BRANCH = "main"
COMMUNITY_SKILLS_REGISTRY_URL = (
    f"https://raw.githubusercontent.com/{COMMUNITY_SKILLS_REPO}/{COMMUNITY_SKILLS_BRANCH}/registry.json"
)
COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS = 30


class CommunitySkillNotFoundError(Exception):
    pass


def get_community_skill_by_slug(slug: str) -> CommunitySkill | None:
    return CommunitySkill.objects.filter(slug=slug, deleted=False).first()


def install_community_skill(
    *,
    team: Team,
    user: User,
    slug: str,
    new_name: str | None = None,
) -> LLMSkill:
    """Copy a community skill into a team as a regular LLMSkill and bump its install counter.

    Raises CommunitySkillNotFoundError if the slug is unknown, and
    LLMSkillDuplicateNameConflictError if the target name already exists in the team.
    """
    community_skill = get_community_skill_by_slug(slug)
    if community_skill is None:
        raise CommunitySkillNotFoundError()

    target_name = validate_skill_name_value(new_name or community_skill.slug)

    files = [
        {"path": f.path, "content": f.content, "content_type": f.content_type} for f in community_skill.files.all()
    ]

    installed = create_skill(
        team,
        user=user,
        name=target_name,
        description=community_skill.description,
        body=community_skill.body,
        license=community_skill.license,
        compatibility=community_skill.compatibility,
        allowed_tools=community_skill.allowed_tools,
        # Stamp provenance so an installed skill can be traced back to its community source.
        metadata={
            **(community_skill.metadata or {}),
            "community_skill_slug": community_skill.slug,
            "community_skill_id": str(community_skill.id),
        },
        files=files or None,
    )

    CommunitySkill.objects.filter(pk=community_skill.pk).update(install_count=F("install_count") + 1)
    return installed


def toggle_community_skill_vote(*, slug: str, user: User) -> tuple[int, bool]:
    """Add or remove the user's upvote. Returns (vote_count, has_voted) after the toggle."""
    community_skill = get_community_skill_by_slug(slug)
    if community_skill is None:
        raise CommunitySkillNotFoundError()

    with transaction.atomic():
        existing = CommunitySkillVote.objects.filter(skill=community_skill, user=user).first()
        if existing is not None:
            existing.delete()
            has_voted = False
        else:
            CommunitySkillVote.objects.create(skill=community_skill, user=user)
            has_voted = True
        vote_count = CommunitySkillVote.objects.filter(skill=community_skill).count()

    return vote_count, has_voted


def _upsert_community_skill(entry: dict[str, Any]) -> bool:
    """Upsert a single registry entry. Returns True if the row was created or updated."""
    slug = entry["slug"]
    source_sha = entry.get("source_sha", "")

    existing = CommunitySkill.objects.filter(slug=slug).first()
    if existing is not None and existing.source_sha and existing.source_sha == source_sha and not existing.deleted:
        return False

    defaults: dict[str, Any] = {
        "name": entry["name"],
        "description": entry["description"],
        "body": entry.get("body", ""),
        "license": entry.get("license", ""),
        "compatibility": entry.get("compatibility", ""),
        "allowed_tools": entry.get("allowed_tools", []),
        "metadata": entry.get("metadata", {}),
        "tags": entry.get("tags", []),
        "trust_tier": entry.get("trust_tier", "community"),
        "author_handle": entry.get("author_handle", ""),
        "github_url": entry.get("github_url", ""),
        "source_sha": source_sha,
        "deleted": False,
    }
    if entry.get("published_at"):
        defaults["published_at"] = entry["published_at"]

    with transaction.atomic():
        skill, _ = CommunitySkill.objects.update_or_create(slug=slug, defaults=defaults)
        if skill.published_at is None:
            CommunitySkill.objects.filter(pk=skill.pk).update(published_at=timezone.now())

        skill.files.all().delete()
        files = entry.get("files", [])
        if files:
            CommunitySkillFile.objects.bulk_create(
                [
                    CommunitySkillFile(
                        skill=skill,
                        path=f["path"],
                        content=f.get("content", ""),
                        content_type=f.get("content_type", "text/plain"),
                    )
                    for f in files
                ]
            )
    return True


def sync_community_skills_from_github(registry_url: str = COMMUNITY_SKILLS_REGISTRY_URL) -> dict[str, int]:
    """Pull the community-skills registry and reconcile the local read-model.

    The registry.json is generated in the repo's CI and embeds each skill's content, so a
    single fetch is enough. Skills missing from the registry are soft-deleted. Returns a
    summary of {synced, skipped, removed} counts.
    """
    response = requests.get(registry_url, timeout=COMMUNITY_SKILLS_SYNC_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("skills", [])

    synced = 0
    skipped = 0
    seen_slugs: set[str] = set()
    for entry in entries:
        slug = entry.get("slug")
        if not slug:
            continue
        seen_slugs.add(slug)
        if _upsert_community_skill(entry):
            synced += 1
        else:
            skipped += 1

    removed = CommunitySkill.objects.filter(deleted=False).exclude(slug__in=seen_slugs).update(deleted=True)

    logger.info("community_skills_synced", synced=synced, skipped=skipped, removed=removed, total=len(entries))
    return {"synced": synced, "skipped": skipped, "removed": removed}
