from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sentry_sdk import capture_exception, set_tag

from posthog.hogql_queries.legacy_compatibility.feature_flag import should_use_hogql_backend_in_insight_serialization
from .filter_to_query import filter_to_query

if TYPE_CHECKING:
    from posthog.models.insight import Insight


@contextmanager
def flagged_conversion_to_query_based(insight: "Insight") -> Iterator[None]:
    """Convert the insight for HogQL-based calculation in place transparently, if conversion is needed."""
    if (
        insight.query is None
        and insight.filters is not None
        and should_use_hogql_backend_in_insight_serialization(insight.team)
    ):
        # TRICKY: We're making it so that a `filters`-based insights is converted to a `query`-based one
        # and treated as such
        try:
            insight.query = filter_to_query(insight.filters).model_dump()
        except:
            # If `filter_to_query` failed, let's capture this and proceed with legacy filters
            set_tag("filter_to_query_todo", True)
            capture_exception()

        try:
            yield
        finally:
            # To prevent the sort-of-faked `query` from accidentally being saved to Postgres, we roll it back
            insight.query = None
    else:
        yield  # No conversion to be done
