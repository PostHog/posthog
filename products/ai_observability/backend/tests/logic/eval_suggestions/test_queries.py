from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError, AIEventsNotFoundError

from products.ai_observability.backend.logic.eval_suggestions import queries


@parameterized.expand([("not_found", AIEventsNotFoundError), ("expired", AIEventsExpiredError)])
def test_missing_ai_events_read_as_no_rows(_name: str, error: type[Exception]) -> None:
    with patch.object(queries, "query_ai_events", side_effect=error("gone")):
        assert queries.run_ai_events_query(MagicMock(pk=1), "SELECT 1 FROM ai_events", {}, "Test") == []
