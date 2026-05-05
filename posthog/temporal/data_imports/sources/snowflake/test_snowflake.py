from unittest import mock

import pytest
from snowflake.connector.errors import DatabaseError, OperationalError

from posthog.temporal.data_imports.sources.generated_configs import (
    SnowflakeAuthTypeConfig,
    SnowflakeSourceConfig,
)
from posthog.temporal.data_imports.sources.snowflake.snowflake import (
    _clean_str,
    _parse_clustering_key_leading_column,
    get_schemas,
)
from posthog.temporal.data_imports.sources.snowflake.source import (
    _CONNECTIVITY_ERROR_MESSAGE,
    SnowflakeSource,
)


@pytest.mark.parametrize(
    "clustering_key,expected",
    [
        # Snowflake stores clustering keys wrapped in LINEAR(...). Unquoted
        # identifiers are uppercased to match the form Snowflake returns from
        # INFORMATION_SCHEMA.COLUMNS — otherwise the source-level membership
        # check `field_name in indexed_cols` misses on every clustering key
        # that was written in lowercase.
        ("LINEAR(created_at)", "CREATED_AT"),
        ("LINEAR(created_at, user_id)", "CREATED_AT"),
        ("LINEAR(CreatedAt)", "CREATEDAT"),
        # Quoted identifiers preserve case sensitivity in Snowflake — strip the
        # quotes and keep the case as-written.
        ('LINEAR("CreatedAt", user_id)', "CreatedAt"),
        ('LINEAR("created_at")', "created_at"),
        # Older / non-LINEAR forms appear unwrapped in INFORMATION_SCHEMA.
        ("created_at", "CREATED_AT"),
        ("  created_at  ", "CREATED_AT"),
        # Function expressions don't accelerate WHERE col >= … on the column
        # they wrap, so we conservatively report no leading column.
        ("LINEAR(DATE_TRUNC('day', created_at))", None),
        # Empty / malformed inputs.
        ("", None),
        (None, None),
        ("LINEAR(", None),
    ],
)
def test_parse_clustering_key_leading_column(clustering_key, expected):
    assert _parse_clustering_key_leading_column(clustering_key) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", ""),
        ("account_id", "account_id"),
        ("  account_id  ", "account_id"),
        (" account_id\t", "account_id"),
        ("\nfoo.bar.snowflakecomputing.com\n", "foo.bar.snowflakecomputing.com"),
    ],
)
def test_clean_str(value, expected):
    assert _clean_str(value) == expected


def _make_config(account_id: str = "  gn58087.ca-central-1.aws  ", **overrides):
    return SnowflakeSourceConfig(
        account_id=account_id,
        database=overrides.get("database", " my_db "),
        warehouse=overrides.get("warehouse", " my_wh "),
        schema=overrides.get("schema", " public "),
        role=overrides.get("role", " ACCOUNTADMIN "),
        auth_type=SnowflakeAuthTypeConfig(
            selection="password",
            user=overrides.get("user", " user1 "),
            password=overrides.get("password", "p w d "),
        ),
    )


def test_get_schemas_strips_whitespace_before_connect():
    # The Snowflake driver URL-encodes connect kwargs into the hostname, so any
    # surrounding whitespace becomes "%20" and the proxy returns 400. Verify
    # that get_schemas trims the user-supplied identifier fields before connect.
    config = _make_config()

    with mock.patch(
        "posthog.temporal.data_imports.sources.snowflake.snowflake.snowflake.connector.connect"
    ) as mock_connect:
        cursor_mock = mock.MagicMock()
        cursor_mock.fetchall.return_value = []
        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor_mock

        get_schemas(config)

    kwargs = mock_connect.call_args.kwargs
    assert kwargs["account"] == "gn58087.ca-central-1.aws"
    assert kwargs["warehouse"] == "my_wh"
    assert kwargs["database"] == "my_db"
    assert kwargs["role"] == "ACCOUNTADMIN"
    assert kwargs["user"] == "user1"
    # The password is intentionally not stripped — it's a secret and may legitimately
    # contain leading/trailing whitespace.
    assert kwargs["password"] == "p w d "

    # The information_schema query parameter is also stripped so the schema
    # search hits the right rows.
    cursor_mock.execute.assert_called_once()
    execute_args = cursor_mock.execute.call_args.args
    assert execute_args[1] == {"schema": "public"}


def test_validate_credentials_returns_friendly_message_for_oserror():
    source = SnowflakeSource()
    config = _make_config(account_id="gn58087.ca-central-1.aws")

    with mock.patch.object(
        source, "get_schemas", side_effect=OSError("Tunnel connection failed: 400 Bad Request")
    ):
        ok, message = source.validate_credentials(config, team_id=1)

    assert ok is False
    assert message == _CONNECTIVITY_ERROR_MESSAGE


def test_validate_credentials_returns_friendly_message_for_operational_error():
    source = SnowflakeSource()
    config = _make_config(account_id="gn58087.ca-central-1.aws")

    with mock.patch.object(source, "get_schemas", side_effect=OperationalError("250001: Could not connect")):
        ok, message = source.validate_credentials(config, team_id=1)

    assert ok is False
    assert message == _CONNECTIVITY_ERROR_MESSAGE


def test_validate_credentials_keeps_known_message_match_for_database_error():
    source = SnowflakeSource()
    config = _make_config(account_id="gn58087.ca-central-1.aws")

    with mock.patch.object(
        source, "get_schemas", side_effect=DatabaseError("Verify the account name is correct please")
    ):
        ok, message = source.validate_credentials(config, team_id=1)

    assert ok is False
    assert message == "Can't find an account with the specified account ID"
