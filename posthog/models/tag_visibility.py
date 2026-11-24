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
    from django.db.models import Exists, OuterRef

    from products.access_control.backend.facade.user_access_control import UserAccessControl


@frozen
class TagVisibilityContext:
    team_id: int
    user_id: int
    user_access_control: UserAccessControl
    object_ref: OuterRef
    """The primary key of the tagged object, for the rule to correlate against."""


TagVisibilityRule = Callable[[TagVisibilityContext], "Exists"]

_filters: dict[str, list[TagVisibilityRule]] = defaultdict(list)
_grants: dict[str, list[TagVisibilityRule]] = defaultdict(list)


def register_tag_visibility_filter(model_label: str, rule: TagVisibilityRule) -> None:
    """Count an object of `model_label` only if `rule` holds, as well as the access-control check."""
    _filters[model_label].append(rule)


def register_tag_visibility_grant(model_label: str, rule: TagVisibilityRule) -> None:
    """Count an object of `model_label` when `rule` holds, even if the access-control check hides it."""
    _grants[model_label].append(rule)


def get_tag_visibility_filters(model_label: str) -> list[TagVisibilityRule]:
    return _filters.get(model_label, [])


def get_tag_visibility_grants(model_label: str) -> list[TagVisibilityRule]:
    return _grants.get(model_label, [])
