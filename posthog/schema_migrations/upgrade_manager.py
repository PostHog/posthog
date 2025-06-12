from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import conversion_to_query_based
from posthog.schema_migrations.upgrade import upgrade

if TYPE_CHECKING:
    from posthog.models.insight import Insight


@contextmanager
def upgrade_query(insight: "Insight") -> Iterator[None]:
    """Replaces filters-based insights with query-based ones and upgrades the query to the latest version if needed."""
    with conversion_to_query_based(insight), upgrade_insight(insight):
        yield


@contextmanager
def upgrade_insight(insight: "Insight") -> Iterator[None]:
    """Upgrade the query to the latest version if needed."""
    insight.query = upgrade(insight.query)
    yield
