import types

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.sync import database_sync_to_async

from products.data_modeling.backend.temporal.activities import utils
from products.data_modeling.backend.temporal.activities.utils import record_worker_time, strip_hostname_from_error


class TestStripHostnameFromError:
    @parameterized.expand(
        [
            # Pattern: "(from host:port)"
            (
                "Code: 159. DB::Exception (from chi-posthog-01.svc.cluster.local:9000): Timeout exceeded",
                "Code: 159. DB::Exception (from [host]): Timeout exceeded",
            ),
            # Pattern: "Received from host:port"
            (
                "Code: 159. DB::Exception: Received from chi-posthog-01.svc.cluster.local:9000. DB::Exception: Timeout exceeded",
                "Code: 159. DB::Exception: Received from [host]. DB::Exception: Timeout exceeded",
            ),
            # Pattern: IP address with port
            (
                "Code: 159. DB::Exception (from 10.0.0.1:9000): Memory limit exceeded",
                "Code: 159. DB::Exception (from [host]): Memory limit exceeded",
            ),
            # Pattern: IP with "Received from"
            (
                "DB::Exception: Received from 192.168.1.100:9000. Query exceeded memory limits",
                "DB::Exception: Received from [host]. Query exceeded memory limits",
            ),
            # Multiple hostnames in one message
            (
                "Error (from chi-01.local:9000): Received from chi-02.local:9440. Failed",
                "Error (from [host]): Received from [host]. Failed",
            ),
            # No hostname - should return unchanged
            (
                "Query failed to materialize: Type coercion error",
                "Query failed to materialize: Type coercion error",
            ),
            # Empty string
            (
                "",
                "",
            ),
            # Hostname in complex ClickHouse error
            (
                "Code: 241. DB::Exception: Memory limit (for query) exceeded: would use 5.00 GiB (from chi-posthog-production-01.clickhouse.svc.cluster.local:9000)",
                "Code: 241. DB::Exception: Memory limit (for query) exceeded: would use 5.00 GiB (from [host])",
            ),
            # IPv6 addresses with port (edge case)
            (
                "DB::Exception (from [::1]:9000): Some error",
                "DB::Exception (from [host]): Some error",
            ),
            # Hostname with subdomain
            (
                "Error (from chi.db.us-east-1.internal.company.com:9000): Query timeout",
                "Error (from [host]): Query timeout",
            ),
            # Non-standard port
            (
                "Received from chi-server.local:8443 - SSL error",
                "Received from [host] - SSL error",
            ),
        ]
    )
    def test_strip_hostname_patterns(self, input_error: str, expected_output: str) -> None:
        result = strip_hostname_from_error(input_error)
        assert result == expected_output


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_record_worker_time_adds_up_over_blocks_and_keeps_a_failed_one(ateam, ajob) -> None:
    readings = iter([100.0, 105.0, 200.0, 207.0, 300.0, 301.0])
    # Only this module's view of the clock is replaced, because the event loop reads time.monotonic too.
    clock = types.SimpleNamespace(monotonic=lambda: next(readings))

    with patch.object(utils, "time", clock):
        async with record_worker_time(ateam.pk, str(ajob.id), attempt=1):
            pass
        with pytest.raises(ValueError, match="query failed"):
            async with record_worker_time(ateam.pk, str(ajob.id), attempt=2):
                raise ValueError("query failed")
        async with record_worker_time(ateam.pk, str(ajob.id)):
            pass

    await database_sync_to_async(ajob.refresh_from_db)()
    assert (ajob.worker_seconds, ajob.attempts) == (13.0, 2)
