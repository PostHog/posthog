"""The library a project secret API key is limited to. A key with no limit reads the whole project."""

from typing import cast
from uuid import UUID

from rest_framework import exceptions
from rest_framework.request import Request

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.scoping import with_team_scope
from posthog.permissions import is_authenticated_via_project_secret_api_key

from .libraries import LibraryNotFound, lock_libraries
from .models import KnowledgeKeyLibrary, KnowledgeLibrary

LIBRARY_DELETED_DETAIL = (
    "The library this project secret API key was limited to no longer exists. Create a new key for another library."
)


def key_library_id(request: Request) -> UUID | None:
    """The one library this request may read. None means the request may read the whole project."""
    if not is_authenticated_via_project_secret_api_key(request):
        return None
    key = cast(ProjectSecretAPIKeyAuthentication, request.successful_authenticator).project_secret_api_key
    limits = list(KnowledgeKeyLibrary.objects.filter(key_id=key.id).values_list("library_id", flat=True)[:1])
    if not limits:
        return None
    if limits[0] is None:
        raise exceptions.PermissionDenied(LIBRARY_DELETED_DETAIL)
    return limits[0]


def readable_library_id(request: Request, requested: UUID | None) -> UUID | None:
    """The library to read for this request. A limited key reads its own library, whatever the caller asked for."""
    limit = key_library_id(request)
    if limit is None:
        return requested
    if requested is not None and requested != limit:
        # The same answer as for an unknown id, so a limited key cannot learn which other libraries exist.
        raise exceptions.NotFound()
    return limit


@with_team_scope()
def limit_key_to_library(team_id: int, key: ProjectSecretAPIKey, library_id: UUID) -> KnowledgeKeyLibrary:
    """Limit a key to one library. Call it inside `transaction.atomic()`, in the transaction that creates the key."""
    # The library lock stops a concurrent delete from leaving this key limited to a library that is gone.
    lock_libraries(team_id)
    if not KnowledgeLibrary.objects.filter(team_id=team_id, id=library_id).exists():
        raise LibraryNotFound()
    return KnowledgeKeyLibrary.objects.create(team_id=team_id, key=key, library_id=library_id)


@with_team_scope()
def key_limits(team_id: int, key_ids: list[str]) -> dict[str, UUID | None]:
    """Library by key id for the limited keys among `key_ids`. None means the key's library was deleted."""
    return dict(
        KnowledgeKeyLibrary.objects.filter(team_id=team_id, key_id__in=key_ids).values_list("key_id", "library_id")
    )
