import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from posthog.temporal.data_imports.sources.postgres.source import PostgresSource
from posthog.temporal.data_imports.sources.supabase.source import SupabaseSource


def _field(name: str) -> SourceFieldInputConfig:
    return next(
        field
        for field in SupabaseSource().get_source_config.fields
        if isinstance(field, SourceFieldInputConfig) and field.name == name
    )


def test_supabase_requires_schema_field():
    schema_field = _field("schema")

    assert schema_field.required is True
    assert schema_field.label == "Schema"
    assert schema_field.caption is None


def test_supabase_host_field_points_at_the_pooler():
    host_field = _field("host")

    assert "pooler.supabase.com" in host_field.placeholder
    assert host_field.caption is not None
    assert "pooler" in host_field.caption.lower()


@pytest.mark.parametrize(
    "host",
    [
        "db.abcdefghijklmnop.supabase.co",
        "DB.ABCDEFGH.SUPABASE.CO",
        "  db.abcdefgh.supabase.co  ",
    ],
)
def test_direct_host_is_rejected_with_pooler_guidance(host):
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials") as super_validate:
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is False
    assert error is not None
    assert "pooler" in error.lower()
    # We short-circuit before attempting the generic Postgres connection.
    super_validate.assert_not_called()


@pytest.mark.parametrize(
    "host",
    [
        "aws-0-us-east-1.pooler.supabase.com",
        "db.example.com",
        "my-db.internal",
    ],
)
def test_pooler_and_other_hosts_delegate_to_postgres(host):
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(True, None)) as super_validate:
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is True
    assert error is None
    super_validate.assert_called_once()
