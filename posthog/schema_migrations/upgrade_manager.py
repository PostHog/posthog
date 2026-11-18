from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from posthog.schema_migrations.upgrade import upgrade

if TYPE_CHECKING:
    from products.product_analytics.backend.facade.models import Insight


@contextmanager
def upgrade_insight(insight: "Insight") -> Iterator[None]:
    """Upgrade the query to the latest version if needed."""
    if insight.query is not None:
        insight.query = upgrade(insight.query)
    yield
