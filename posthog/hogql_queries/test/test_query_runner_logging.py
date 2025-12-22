from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from pydantic import BaseModel

from posthog.schema import GenericCachedQueryResponse

from posthog.hogql_queries.query_runner import ExecutionMode, QueryRunner


class DummyQuery(BaseModel):
    kind: str = "DummyQuery"


class DummyResponse(BaseModel):
    results: str = "ok"
    error: str | None = None
    errors: list[str] | None = None


class DummyCachedResponse(GenericCachedQueryResponse):
    results: str | None = None
    error: str | None = None
    errors: list[str] | None = None


class DummyQueryRunner(QueryRunner[DummyQuery, DummyResponse, DummyCachedResponse]):  # type: ignore
    query: DummyQuery
    response: DummyResponse
    cached_response: DummyCachedResponse

    def __init__(
        self,
        *args: Any,
        response_error: str | None = None,
        response_errors: list[str] | None = None,
        raise_exception: bool = False,
        **kwargs: Any,
    ):
        self._response_error = response_error
        self._response_errors = response_errors
        self._raise_exception = raise_exception
        super().__init__(*args, **kwargs)

    def _calculate(self) -> DummyResponse:
        if self._raise_exception:
            raise ValueError("boom")
        return DummyResponse(error=self._response_error, errors=self._response_errors)

    def to_query(self):
        raise NotImplementedError()

    def to_actors_query(self, *args, **kwargs):
        raise NotImplementedError()


class TestQueryRunnerLogging(BaseTest):
    def test_has_error_true_when_response_contains_error_string(self):
        runner = DummyQueryRunner(query=DummyQuery(), team=self.team, response_error="bad")

        with patch("posthoganalytics.capture") as capture_mock:
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)

        props = capture_mock.call_args.kwargs["properties"]
        self.assertTrue(props["has_error"])
        self.assertFalse(props["cache_hit"])

    def test_has_error_true_when_response_contains_errors_list(self):
        runner = DummyQueryRunner(query=DummyQuery(), team=self.team, response_errors=["boom"])

        with patch("posthoganalytics.capture") as capture_mock:
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)

        props = capture_mock.call_args.kwargs["properties"]
        self.assertTrue(props["has_error"])
        self.assertFalse(props["cache_hit"])

    def test_exception_still_records_has_error(self):
        runner = DummyQueryRunner(query=DummyQuery(), team=self.team, raise_exception=True)

        with patch("posthoganalytics.capture") as capture_mock:
            with self.assertRaises(ValueError):
                runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)

        self.assertEqual(capture_mock.call_count, 1)
        props = capture_mock.call_args.kwargs["properties"]
        self.assertTrue(props["has_error"])
        self.assertEqual(props["error_type"], "ValueError")
        self.assertFalse(props["cache_hit"])
