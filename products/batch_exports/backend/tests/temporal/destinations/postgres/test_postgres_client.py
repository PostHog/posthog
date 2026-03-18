import pytest

from psycopg.errors import SerializationFailure

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    PostgreSQLClient,
    PostgreSQLTransactionError,
    remove_invalid_json,
    run_in_retryable_transaction,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


@pytest.mark.parametrize(
    "input_data, expected_data",
    [
        (rb"Hello \uD83D\uDE00 World", rb"Hello \uD83D\uDE00 World"),  # Valid emoji pair (😀)
        (rb"Bad \uD800 unpaired high", b"Bad  unpaired high"),  # Unpaired high surrogate
        (rb"Bad \uDC00 unpaired low", b"Bad  unpaired low"),  # Unpaired low surrogate
        (
            rb"\uD83C\uDF89 Party \uD800 \uD83D\uDE0A mixed",
            rb"\uD83C\uDF89 Party  \uD83D\uDE0A mixed",
        ),  # Mix of valid pairs and unpaired
        (rb"Hello \u0000 World", b"Hello  World"),  # \u0000 is not a valid JSON character in PostgreSQL
        (b"Hello \\u0000 World", b"Hello  World"),  # this is the same as the above
        (b"Hello \\\\u0000 World", b"Hello \\\\u0000 World"),  # \\u0000 is escaped
    ],
)
def test_remove_invalid_json(input_data, expected_data):
    assert remove_invalid_json(input_data) == expected_data


async def test_run_in_retryable_transaction_raises_non_retryable_error_after_max_retries(
    postgres_config, setup_postgres_test_db
):
    """Test that `run_in_retryable_transaction` retries on serialization failure and eventually raises a
    `PostgreSQLTransactionError`.
    """

    attempt_count = 0

    async def raise_serialization_failure():
        nonlocal attempt_count
        attempt_count += 1
        raise SerializationFailure("test error")

    postgres_client = PostgreSQLClient(
        user=postgres_config["user"],
        password=postgres_config["password"],
        database=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        has_self_signed_cert=False,
    )

    async with postgres_client.connect() as pg_client:
        with pytest.raises(
            PostgreSQLTransactionError, match="A transaction failed to complete after 3 attempts: test error"
        ):
            await run_in_retryable_transaction(pg_client.connection, raise_serialization_failure)

    assert attempt_count == 3


async def test_run_in_retryable_transaction_retries_successfully_on_serialization_failure(
    postgres_config, setup_postgres_test_db
):
    """Test that `run_in_retryable_transaction` retries on serialization failure and eventually succeeds."""

    attempt_count = 0

    async def raise_serialization_failure():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 2:
            return "success"
        raise SerializationFailure("test error")

    postgres_client = PostgreSQLClient(
        user=postgres_config["user"],
        password=postgres_config["password"],
        database=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        has_self_signed_cert=False,
    )

    async with postgres_client.connect() as pg_client:
        result = await run_in_retryable_transaction(pg_client.connection, raise_serialization_failure)
        assert result == "success"

    assert attempt_count == 2


async def test_run_in_retryable_transaction_raises_error_if_fn_raises_non_serialization_failure(
    postgres_config, setup_postgres_test_db
):
    """Test that `run_in_retryable_transaction` raises an error if the function raises a non-serialization failure."""

    attempt_count = 0

    async def raise_error():
        nonlocal attempt_count
        attempt_count += 1
        raise ValueError("test error")

    postgres_client = PostgreSQLClient(
        user=postgres_config["user"],
        password=postgres_config["password"],
        database=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        has_self_signed_cert=False,
    )

    async with postgres_client.connect() as pg_client:
        with pytest.raises(ValueError, match="test error"):
            await run_in_retryable_transaction(pg_client.connection, raise_error)

    assert attempt_count == 1
