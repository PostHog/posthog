"""Page planning for the property list when it is sorted by 30-day query count.

The list has two segments. Used properties come from the usage map, which is small, so Python
sorts them by count. Unused properties are most of a large project, so Postgres pages them by name.
"""

import uuid
from collections.abc import Sequence

from django.db.models import TextChoices

from rest_framework import status
from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen

# Above this many matching definitions the list refuses to sort by usage, and asks for a narrower filter.
MAX_DEFINITIONS_FOR_USAGE_ORDERING = 250_000


class PropertyDefinitionOrdering(TextChoices):
    MOST_QUERIED = "-query_usage", "Most queried first"
    LEAST_QUERIED = "query_usage", "Least queried first"


class TooManyPropertiesToOrderByUsage(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "too_many_properties_to_order_by_usage"
    default_detail = "There are too many properties to sort by queries. Search or filter the list, then sort again."


@frozen
class UsedProperty:
    id: uuid.UUID
    name: str
    count: int


@frozen
class UsagePagePlan:
    used: list[UsedProperty]
    unused_offset: int
    unused_limit: int
    unused_first: bool


def plan_usage_page(
    ordering: PropertyDefinitionOrdering,
    used: Sequence[UsedProperty],
    total: int,
    offset: int,
    limit: int,
) -> UsagePagePlan:
    """Pick the rows of one page from the used segment and the unused segment.

    `total` counts all matching definitions, so `total - len(used)` of them are unused.
    Ties sort by name and then id, so every row has one stable position across pages.
    """
    unused_total = max(0, total - len(used))
    if ordering == PropertyDefinitionOrdering.MOST_QUERIED:
        ranked = sorted(used, key=lambda row: (-row.count, row.name, str(row.id)))
        page_used = ranked[offset : offset + limit]
        unused_offset = max(0, offset - len(ranked))
        unused_limit = max(0, min(limit - len(page_used), unused_total - unused_offset))
        return UsagePagePlan(used=page_used, unused_offset=unused_offset, unused_limit=unused_limit, unused_first=False)

    ranked = sorted(used, key=lambda row: (row.count, row.name, str(row.id)))
    unused_limit = max(0, min(limit, unused_total - offset))
    used_offset = max(0, offset - unused_total)
    page_used = ranked[used_offset : used_offset + limit - unused_limit]
    return UsagePagePlan(used=page_used, unused_offset=offset, unused_limit=unused_limit, unused_first=True)
