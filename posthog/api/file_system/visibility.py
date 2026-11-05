"""Per-product visibility filters for file system rows, beyond project RBAC.

A product whose objects have visibility rules of their own (a canvas follows its channel) registers a
filter from its app config. The file system applies every registered filter to each read, so a row lists
only when the product lets this person see the object behind it.
"""

from collections.abc import Callable
from typing import Any

from django.db.models import QuerySet

# (rows, request, project_id): the request carries the user and the credential, since a product's rules may
# depend on both (a sandbox token does not inherit its user's private spaces).
FileSystemVisibilityFilter = Callable[[QuerySet, Any, int], QuerySet]

_VISIBILITY_FILTERS: dict[str, FileSystemVisibilityFilter] = {}


def register_file_system_visibility_filter(type_string: str, filter_fn: FileSystemVisibilityFilter) -> None:
    """Register how rows of `type_string` narrow by viewer. The filter gets the rows, the request and the project id."""
    _VISIBILITY_FILTERS[type_string] = filter_fn


def apply_file_system_visibility_filters(queryset: QuerySet, *, request: Any, project_id: int) -> QuerySet:
    for filter_fn in _VISIBILITY_FILTERS.values():
        queryset = filter_fn(queryset, request, project_id)
    return queryset
