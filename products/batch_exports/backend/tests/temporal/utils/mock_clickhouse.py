import re
import json
import typing
import dataclasses

from unittest import mock
from unittest.mock import AsyncMock

from posthog.temporal.common.clickhouse import ClickHouseClient

type JsonResponseSequence = list[list[dict[str, typing.Any]]]


@dataclasses.dataclass
class CapturedCall:
    query: str
    query_parameters: dict[str, typing.Any] | None
    query_id: str | None


class MockClickHouseClient:
    """Mock ClickHouse client that captures query calls and their metadata.

    Supports both write queries (via `execute_query`) and read queries
    (via `read_query_as_jsonl`).  Each call is recorded in `self.calls`.

    Set `read_query_as_jsonl_responses` to a list of responses (one per
    call).  The last response is reused for any additional calls beyond
    the list length.  An empty list returns `[]` for every call.
    """

    def __init__(
        self,
        read_query_as_jsonl_responses: JsonResponseSequence | None = None,
    ):
        self.calls: list[CapturedCall] = []
        self.mock_client = AsyncMock(spec=ClickHouseClient)
        self.mock_client.read_query_as_jsonl = self._capture_read_query_as_jsonl
        self.mock_client.execute_query = self._capture_execute_query
        self.mock_client_cm = mock.AsyncMock()
        self.mock_client_cm.__aenter__.return_value = self.mock_client
        self.mock_client_cm.__aexit__.return_value = None

        # Return values for read_query_as_jsonl.
        # Each call pops from the front; the last value is reused for any extra calls.
        self.read_query_as_jsonl_responses: JsonResponseSequence = read_query_as_jsonl_responses or []

    # -- recording helpers ---------------------------------------------------

    def _snapshot_call(self, query: str, query_parameters: dict | None, query_id: str | None) -> None:
        self.calls.append(
            CapturedCall(
                query=query,
                query_parameters=query_parameters,
                query_id=query_id,
            )
        )

    async def _capture_read_query_as_jsonl(self, query, query_parameters=None, query_id=None):
        self._snapshot_call(query, query_parameters, query_id)
        if not self.read_query_as_jsonl_responses:
            return []
        if len(self.read_query_as_jsonl_responses) == 1:
            return self.read_query_as_jsonl_responses[0]
        return self.read_query_as_jsonl_responses.pop(0)

    async def _capture_execute_query(self, query, *data, query_parameters=None, query_id=None, **kwargs):
        self._snapshot_call(query, query_parameters, query_id)

    # -- assertion helpers ---------------------------------------------------

    def expect_query_count(self, expected: int) -> None:
        """Assert that exactly `expected` queries were captured."""
        assert len(self.calls) == expected, f"Expected {expected} queries, got {len(self.calls)}"

    def expect_select_from_table(self, table_name: str, call_index: int = 0) -> None:
        """Assert that a captured query selects from `table_name`."""
        query = self.calls[call_index].query
        pattern = rf"FROM\s+{re.escape(table_name)}"
        assert re.search(pattern, query, re.IGNORECASE), f"Query does not select FROM {table_name}"

    def expect_properties_in_log_comment(
        self, properties: dict[str, typing.Any], call_index: int | None = None
    ) -> None:
        """Assert that the `log_comment` query parameter contains `properties`.

        If `call_index` is `None` (default), checks all captured calls.
        """
        indices = range(len(self.calls)) if call_index is None else [call_index]
        for i in indices:
            query_parameters = self.calls[i].query_parameters or {}
            raw = query_parameters.get("log_comment")
            assert raw is not None, f"Call {i}: log_comment not found in query_parameters"
            log_comment = json.loads(raw) if isinstance(raw, str) else raw
            for key, value in properties.items():
                actual = log_comment.get(key)
                assert actual == value, f"Call {i}: expected log_comment[{key}]={value!r}, got {actual!r}"

    def expect_all_calls_have_query_id(self) -> None:
        """Assert that every captured call has a non-None query_id."""
        for i, call in enumerate(self.calls):
            assert call.query_id is not None, f"Call {i} has no query_id"

    def expect_unique_query_ids(self) -> None:
        """Assert that all captured query_ids are unique."""
        query_ids = [call.query_id for call in self.calls]
        assert len(query_ids) == len(set(query_ids)), f"Duplicate query_ids found: {query_ids}"
