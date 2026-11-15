"""Library membership. A library does not own sources or repositories. Deleting it drops the links only."""

from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, connection, transaction
from django.db.models import Count

import structlog

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.scoping import with_team_scope
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team

from .constants import DEFAULT_LIBRARY_NAME, MAX_LIBRARIES_PER_TEAM
from .models import (
    KnowledgeLibrary,
    KnowledgeLibraryRepository,
    KnowledgeLibrarySource,
    KnowledgeSource,
    TeamBusinessKnowledgeConfig,
)

logger = structlog.get_logger(__name__)


class LibraryNotFound(Exception):
    """The library id is missing on this project."""


class LibraryRejected(Exception):
    """A field the caller sent cannot be saved. `errors` is a DRF validation map."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__(next(iter(errors.values()), "Invalid library."))


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise LibraryRejected({"name": "Enter a name."})
    if len(cleaned) > 255:
        raise LibraryRejected({"name": "Name must be 255 characters or fewer."})
    return cleaned


def _normalize_repo(repo: str) -> str:
    return repo.strip().lower()


def _lock_libraries(team_id: int) -> None:
    # Transaction-scoped. Every library write takes it before any row lock, so two writes never lock rows in opposite
    # orders, and the library count check cannot race another create.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"business_knowledge_libraries:{team_id}"],
        )


def lock_libraries(team_id: int) -> None:
    """Take the project's library lock for a write outside this module. Call it inside `transaction.atomic()`."""
    _lock_libraries(resolve_effective_team_id(team_id))


def _require_library_locked(team_id: int, library_id: UUID) -> None:
    if not KnowledgeLibrary.objects.filter(team_id=team_id, id=library_id).exists():
        raise LibraryNotFound()


@with_team_scope()
def list_libraries(team_id: int) -> list[KnowledgeLibrary]:
    team_id = resolve_effective_team_id(team_id)
    return list(
        KnowledgeLibrary.objects.filter(team_id=team_id)
        .annotate(source_count=Count("source_links"))
        .order_by("-is_default", "name", "id")
    )


@with_team_scope()
def get_library(team_id: int, library_id: UUID) -> KnowledgeLibrary:
    team_id = resolve_effective_team_id(team_id)
    try:
        return KnowledgeLibrary.objects.annotate(source_count=Count("source_links")).get(id=library_id, team_id=team_id)
    except KnowledgeLibrary.DoesNotExist:
        raise LibraryNotFound() from None


def visible_repos(team_id: int, library_ids: list[UUID], allowlist: set[str]) -> dict[UUID, list[str]]:
    """Repo names on these libraries that this environment's allowlist still permits."""
    if not library_ids or not allowlist:
        return {library_id: [] for library_id in library_ids}
    canonical_team_id = resolve_effective_team_id(team_id)
    grouped: dict[UUID, list[str]] = {library_id: [] for library_id in library_ids}
    rows = (
        KnowledgeLibraryRepository.objects.filter(
            team_id=canonical_team_id,
            library_id__in=library_ids,
            repo__in=allowlist,
        )
        .order_by("repo")
        .values_list("library_id", "repo")
    )
    for library_id, repo in rows:
        grouped[library_id].append(repo)
    return grouped


@with_team_scope()
def create_library(team_id: int, name: str) -> KnowledgeLibrary:
    team_id = resolve_effective_team_id(team_id)
    cleaned = _clean_name(name)
    with transaction.atomic():
        _lock_libraries(team_id)
        if KnowledgeLibrary.objects.filter(team_id=team_id).count() >= MAX_LIBRARIES_PER_TEAM:
            raise LibraryRejected({"name": f"This project already has {MAX_LIBRARIES_PER_TEAM} libraries."})
        if KnowledgeLibrary.objects.filter(team_id=team_id, name__iexact=cleaned).exists():
            raise LibraryRejected({"name": "A library with this name already exists."})
        try:
            with transaction.atomic():
                library = KnowledgeLibrary.objects.create(team_id=team_id, name=cleaned, is_default=False)
        except IntegrityError:
            raise LibraryRejected({"name": "A library with this name already exists."}) from None
    library.source_count = 0  # type: ignore[attr-defined]
    return library


@with_team_scope()
def rename_library(team_id: int, library_id: UUID, name: str) -> KnowledgeLibrary:
    team_id = resolve_effective_team_id(team_id)
    cleaned = _clean_name(name)
    with transaction.atomic():
        _lock_libraries(team_id)
        library = get_library(team_id, library_id)
        if cleaned == library.name:
            return library
        if KnowledgeLibrary.objects.filter(team_id=team_id, name__iexact=cleaned).exclude(id=library.id).exists():
            raise LibraryRejected({"name": "A library with this name already exists."})
        library.name = cleaned
        try:
            with transaction.atomic():
                library.save(update_fields=["name", "updated_at"])
        except IntegrityError:
            raise LibraryRejected({"name": "A library with this name already exists."}) from None
    return library


@with_team_scope()
def delete_library(team_id: int, library_id: UUID) -> None:
    team_id = resolve_effective_team_id(team_id)
    library = get_library(team_id, library_id)
    with transaction.atomic():
        _lock_libraries(team_id)
        library.delete()


def _source_ids_for_library(team_id: int, library_id: UUID) -> list[str]:
    return [
        str(source_id)
        for source_id in KnowledgeLibrarySource.objects.filter(team_id=team_id, library_id=library_id)
        .order_by("source_id")
        .values_list("source_id", flat=True)
    ]


def _log_membership(
    *,
    team_id: int,
    item_id: UUID,
    scope: str,
    name: str,
    field: str,
    before: list[str],
    after: list[str],
) -> None:
    if before == after:
        return
    log_activity(
        organization_id=None,
        team_id=team_id,
        user=get_current_user(),
        was_impersonated=bool(get_was_impersonated()),
        item_id=item_id,
        scope=scope,
        activity="updated",
        detail=Detail(
            name=name,
            changes=[Change(type=scope, action="changed", field=field, before=before, after=after)],
        ),
    )


@with_team_scope()
def replace_library_sources(team_id: int, library_id: UUID, source_ids: list[UUID]) -> KnowledgeLibrary:
    team_id = resolve_effective_team_id(team_id)
    library = get_library(team_id, library_id)
    requested = list(dict.fromkeys(source_ids))
    found = set(KnowledgeSource.objects.filter(team_id=team_id, id__in=requested).values_list("id", flat=True))
    if set(requested) != found:
        raise LibraryRejected({"source_ids": "One or more sources were not found."})
    after = [str(source_id) for source_id in requested]
    with transaction.atomic():
        _lock_libraries(team_id)
        _require_library_locked(team_id, library.id)
        before = _source_ids_for_library(team_id, library.id)
        if before == sorted(after):
            return library
        KnowledgeLibrarySource.objects.filter(team_id=team_id, library=library).delete()
        KnowledgeLibrarySource.objects.bulk_create(
            [KnowledgeLibrarySource(team_id=team_id, library=library, source_id=source_id) for source_id in requested]
        )
        _log_membership(
            team_id=team_id,
            item_id=library.id,
            scope="KnowledgeLibrary",
            name=f"Library '{library.name}' updated",
            field="sources",
            before=before,
            after=sorted(after),
        )
    return get_library(team_id, library.id)


@with_team_scope()
def replace_library_repos(
    team_id: int,
    library_id: UUID,
    repos: list[str],
    *,
    environment_allowlist: set[str],
) -> KnowledgeLibrary:
    """Replace this environment's repo links. Links for repos only another environment allows stay."""
    team_id = resolve_effective_team_id(team_id)
    library = get_library(team_id, library_id)
    requested: list[str] = []
    for repo in repos:
        normalized = _normalize_repo(repo)
        if not normalized or normalized not in environment_allowlist:
            raise LibraryRejected({"repos": "Choose repositories that are selected for this environment."})
        if normalized not in requested:
            requested.append(normalized)
    requested_set = set(requested)
    with transaction.atomic():
        _lock_libraries(team_id)
        _require_library_locked(team_id, library.id)
        current_visible = set(
            KnowledgeLibraryRepository.objects.filter(
                team_id=team_id,
                library=library,
                repo__in=environment_allowlist,
            ).values_list("repo", flat=True)
        )
        if current_visible == requested_set:
            return library
        KnowledgeLibraryRepository.objects.filter(
            team_id=team_id,
            library=library,
            repo__in=environment_allowlist,
        ).exclude(repo__in=requested_set).delete()
        already = set(
            KnowledgeLibraryRepository.objects.filter(team_id=team_id, library=library).values_list("repo", flat=True)
        )
        KnowledgeLibraryRepository.objects.bulk_create(
            [
                KnowledgeLibraryRepository(team_id=team_id, library=library, repo=repo)
                for repo in sorted(requested_set - already)
            ]
        )
        _log_membership(
            team_id=team_id,
            item_id=library.id,
            scope="KnowledgeLibrary",
            name=f"Library '{library.name}' updated",
            field="repos",
            before=sorted(current_visible),
            after=sorted(requested_set),
        )
    return get_library(team_id, library.id)


def _library_ids_for_source(team_id: int, source_id: UUID) -> list[str]:
    return [
        str(library_id)
        for library_id in KnowledgeLibrarySource.objects.filter(team_id=team_id, source_id=source_id)
        .order_by("library_id")
        .values_list("library_id", flat=True)
    ]


@with_team_scope()
def require_libraries(team_id: int, library_ids: list[UUID]) -> None:
    team_id = resolve_effective_team_id(team_id)
    requested = set(library_ids)
    found = set(KnowledgeLibrary.objects.filter(team_id=team_id, id__in=requested).values_list("id", flat=True))
    if requested != found:
        raise LibraryRejected({"library_ids": "One or more libraries were not found."})


@with_team_scope()
def replace_source_libraries(
    team_id: int, source: KnowledgeSource, library_ids: list[UUID], *, skip_missing: bool = False
) -> None:
    """`skip_missing` drops a library deleted since the caller validated it, as if the delete ran after this call."""
    team_id = resolve_effective_team_id(team_id)
    requested = list(dict.fromkeys(library_ids))
    with transaction.atomic():
        _lock_libraries(team_id)
        if skip_missing:
            existing = set(
                KnowledgeLibrary.objects.filter(team_id=team_id, id__in=requested).values_list("id", flat=True)
            )
            requested = [library_id for library_id in requested if library_id in existing]
        else:
            require_libraries(team_id, requested)
        before = _library_ids_for_source(team_id, source.id)
        after = sorted(str(library_id) for library_id in requested)
        if before == after:
            return
        KnowledgeLibrarySource.objects.filter(team_id=team_id, source=source).delete()
        KnowledgeLibrarySource.objects.bulk_create(
            [KnowledgeLibrarySource(team_id=team_id, library_id=library_id, source=source) for library_id in requested]
        )
        _log_membership(
            team_id=team_id,
            item_id=source.id,
            scope="KnowledgeSource",
            name=f"Knowledge source '{source.name}' updated",
            field="library_ids",
            before=before,
            after=after,
        )


@with_team_scope()
def ensure_default_library(team_id: int) -> KnowledgeLibrary | None:
    """The library new learned sources join. None when the project is already at the library cap and has no default."""
    team_id = resolve_effective_team_id(team_id)
    existing = KnowledgeLibrary.objects.filter(team_id=team_id, is_default=True).first()
    if existing is not None:
        return existing
    with transaction.atomic():
        _lock_libraries(team_id)
        existing = KnowledgeLibrary.objects.filter(team_id=team_id, is_default=True).first()
        if existing is not None:
            return existing
        named = KnowledgeLibrary.objects.filter(team_id=team_id, name__iexact=DEFAULT_LIBRARY_NAME).first()
        if named is not None:
            named.is_default = True
            named.save(update_fields=["is_default", "updated_at"])
            return named
        if KnowledgeLibrary.objects.filter(team_id=team_id).count() >= MAX_LIBRARIES_PER_TEAM:
            # A learned document must still land. It stays unfiled until a library is removed.
            logger.warning("business_knowledge.default_library_skipped_at_cap", team_id=team_id)
            return None
        return KnowledgeLibrary.objects.create(team_id=team_id, name=DEFAULT_LIBRARY_NAME, is_default=True)


@with_team_scope()
def file_new_learned_source(*, team_id: int, source_id: UUID) -> None:
    """Link a learned source the first time it is inserted. A later call is not made, so removing the link sticks."""
    team_id = resolve_effective_team_id(team_id)
    library = ensure_default_library(team_id)
    if library is None:
        return
    if KnowledgeLibrarySource.objects.filter(team_id=team_id, library=library, source_id=source_id).exists():
        return
    KnowledgeLibrarySource.objects.create(team_id=team_id, library=library, source_id=source_id)


@with_team_scope()
def library_repo_names(team_id: int, library_id: UUID) -> set[str]:
    team_id = resolve_effective_team_id(team_id)
    if not KnowledgeLibrary.objects.filter(team_id=team_id, id=library_id).exists():
        raise LibraryNotFound()
    return set(
        KnowledgeLibraryRepository.objects.filter(team_id=team_id, library_id=library_id).values_list("repo", flat=True)
    )


def project_allowed_repos(team: Team) -> set[str]:
    """Repos any environment of this project still allows. Used when one environment's allowlist changes."""
    canonical_id = team.parent_team_id or team.id
    team_ids = list(Team.objects.filter(id=canonical_id).values_list("id", flat=True)) + list(
        Team.objects.filter(parent_team_id=canonical_id).values_list("id", flat=True)
    )
    allowed: set[str] = set()
    for config in TeamBusinessKnowledgeConfig.objects.filter(team_id__in=team_ids).only("github_repos"):
        repos = config.github_repos
        if not isinstance(repos, list):
            continue
        for repo in repos:
            if isinstance(repo, str) and repo.strip():
                allowed.add(repo.strip().lower())
    return allowed


@with_team_scope()
def prune_repository_links(team_id: int, allowed_repos: set[str]) -> None:
    team_id = resolve_effective_team_id(team_id)
    stale = KnowledgeLibraryRepository.objects.filter(team_id=team_id)
    if allowed_repos:
        stale = stale.exclude(repo__in=allowed_repos)
    stale.delete()
