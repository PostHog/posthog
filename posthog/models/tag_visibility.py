"""Visibility rules a product adds to tag usage counts, on top of the generic access-control check.

Some products hide rows by rules of their own, such as task channel membership or the account a
row belongs to. Tag counts live in core and cannot import those rules, so each product registers
them here from its AppConfig.ready().
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from products.access_control.backend.facade.user_access_control import UserAccessControl

TagVisibilityResolver = Callable[[int, int, "UserAccessControl"], "QuerySet"]
"""Takes a team id, a user id and the user's access control, and returns the rows that decide visibility."""


@frozen
class TagVisibilityRule:
    resolver: TagVisibilityResolver
    object_id_field: str
    """The column of the resolver's rows that holds the tagged object's primary key."""


_filters: dict[str, list[TagVisibilityRule]] = defaultdict(list)
_grants: dict[str, list[TagVisibilityRule]] = defaultdict(list)


def register_tag_visibility_filter(
    model_label: str, resolver: TagVisibilityResolver, *, object_id_field: str = "pk"
) -> None:
    """Count an object of `model_label` only if `resolver` returns it, as well as passing the access-control check."""
    _filters[model_label].append(TagVisibilityRule(resolver=resolver, object_id_field=object_id_field))


def register_tag_visibility_grant(
    model_label: str, resolver: TagVisibilityResolver, *, object_id_field: str = "pk"
) -> None:
    """Count an object of `model_label` that `resolver` returns, even if the access-control check hides it."""
    _grants[model_label].append(TagVisibilityRule(resolver=resolver, object_id_field=object_id_field))


def get_tag_visibility_filters(model_label: str) -> list[TagVisibilityRule]:
    return _filters.get(model_label, [])


def get_tag_visibility_grants(model_label: str) -> list[TagVisibilityRule]:
    return _grants.get(model_label, [])
