import pytest
from posthog.test.base import run_clickhouse_statement_in_parallel

from clickhouse_driver.errors import ServerException


def test_run_clickhouse_statement_in_parallel_propagates_errors():
    with pytest.raises(ServerException):
        run_clickhouse_statement_in_parallel(["SELECT invalid syntax!!!"])
