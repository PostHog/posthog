from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.api.query import CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit

from .trace_fixtures import PAGE_BOUNDS, T0, post_page_read

PAGE_READS = ["previews", "people", "sentiment"]
BOUNDED_READS = ["people", "sentiment"]
LONG_TRACE_ID = "t" * 300


def page_body(read: str, trace_ids: list[str]) -> dict[str, object]:
    return {"trace_ids": trace_ids} if read == "previews" else {"trace_ids": trace_ids, **PAGE_BOUNDS}


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestTracePageReads(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([(read,) for read in PAGE_READS])
    def test_a_key_without_the_scope_is_refused(self, read: str) -> None:
        response = post_page_read(self, read, page_body(read, ["trace-1"]), scopes=["query:read"])

        assert response.status_code == 403

    @parameterized.expand(
        [
            (
                "previews",
                {"input": None, "output": None, "inputMissingReason": None, "outputMissingReason": None},
            ),
            ("people", {"person": None}),
            ("sentiment", {"sentiment": None}),
        ]
    )
    def test_a_trace_id_of_any_length_is_read(self, read: str, empty_cells: dict[str, None]) -> None:
        response = post_page_read(self, read, page_body(read, [LONG_TRACE_ID]))

        assert (response.status_code, response.json()) == (
            200,
            {"items": [{"traceId": LONG_TRACE_ID, **empty_cells}]},
        )

    @parameterized.expand(
        [
            *(
                (f"{read} with {name}", read, page_body(read, trace_ids))
                for read in PAGE_READS
                for name, trace_ids in [
                    ("no trace ids", []),
                    ("too many trace ids", [f"trace-{index}" for index in range(101)]),
                ]
            ),
            ("people without the earliest bound", "people", {"trace_ids": ["trace-1"], "latest_created_at": T0}),
            ("sentiment without the latest bound", "sentiment", {"trace_ids": ["trace-1"], "earliest_created_at": T0}),
            *(
                (
                    f"{read} with bounds {name}",
                    read,
                    {"trace_ids": ["trace-1"], "earliest_created_at": earliest, "latest_created_at": latest},
                )
                for read in BOUNDED_READS
                for name, earliest, latest in [
                    ("out of order", T0, T0 - timedelta(minutes=1)),
                    ("at the start of time", "0001-01-01T00:05:00Z", "0001-01-01T00:05:00Z"),
                    ("at the end of time", "9999-12-31T00:00:00Z", "9999-12-31T00:00:00Z"),
                    ("reaching the end of time", T0, "9999-12-31T00:00:00Z"),
                ]
            ),
        ]
    )
    def test_a_bad_body_is_a_400(self, _name: str, read: str, body: dict[str, object]) -> None:
        assert post_page_read(self, read, body).status_code == 400

    @parameterized.expand(
        [
            (f"{read} with a {reader}", read, scopes, exhausted_limit)
            for reader, scopes, exhausted_limit in [
                ("browser session", None, "app_per_org"),
                ("personal api key", ["llm_analytics:read"], "api_per_team"),
            ]
            for read in PAGE_READS
        ]
    )
    def test_a_full_query_slot_is_a_429(
        self, _name: str, read: str, scopes: list[str] | None, exhausted_limit: str
    ) -> None:
        def use(limiter: RateLimit, *args: object, **kwargs: object) -> ConcurrencySlot | None:
            if limiter.limit_name == exhausted_limit:
                raise ConcurrencyLimitExceeded(exhausted_limit)
            return None

        with (
            patch("posthog.clickhouse.client.limit.TEST", False),
            patch.object(RateLimit, "use", autospec=True, side_effect=use),
        ):
            response = post_page_read(self, read, page_body(read, ["trace-1"]), scopes=scopes)

        assert response.status_code == 429
        assert response["Retry-After"] == str(CONCURRENCY_LIMIT_RETRY_AFTER_SECONDS)
