from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from django.core.management import call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def organization():
    return create_organization("test org")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


@pytest.fixture
def team_2(organization):
    return create_team(organization=organization)


def _create_source(team, source_type="Postgres"):
    return ExternalDataSource.objects.create(team=team, source_type=source_type, job_inputs={})


def _create_schema(source, name="test_table", should_sync=True, latest_error=None):
    return ExternalDataSchema.objects.create(
        name=name,
        team=source.team,
        source=source,
        should_sync=should_sync,
        latest_error=latest_error,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
    )


@patch("posthog.management.commands.reenable_schemas_by_error.update_should_sync")
class TestReenableSchemasByError:
    def test_reenables_matching_schemas(self, mock_update, team):
        source = _create_source(team)
        schema = _create_schema(
            source,
            should_sync=False,
            latest_error="OperationalError: connection is insecure (try using sslmode=require)",
        )

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        mock_update.assert_called_once_with(schema_id=str(schema.id), team_id=team.id, should_sync=True)

    def test_case_insensitive_match(self, mock_update, team):
        source = _create_source(team)
        _create_schema(
            source,
            should_sync=False,
            latest_error="OperationalError: CONNECTION IS INSECURE",
        )

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        assert mock_update.call_count == 1

    def test_default_is_dry_run(self, mock_update, team):
        source = _create_source(team)
        _create_schema(
            source,
            should_sync=False,
            latest_error="connection is insecure",
        )

        call_command("reenable_schemas_by_error", "connection is insecure")

        mock_update.assert_not_called()

    def test_skips_already_enabled_schemas(self, mock_update, team):
        source = _create_source(team)
        _create_schema(
            source,
            should_sync=True,
            latest_error="connection is insecure",
        )

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        mock_update.assert_not_called()

    def test_skips_schemas_with_different_error(self, mock_update, team):
        source = _create_source(team)
        _create_schema(
            source,
            should_sync=False,
            latest_error="password authentication failed",
        )

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        mock_update.assert_not_called()

    def test_skips_deleted_schemas(self, mock_update, team):
        source = _create_source(team)
        schema = _create_schema(
            source,
            should_sync=False,
            latest_error="connection is insecure",
        )
        schema.deleted = True
        schema.save()

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        mock_update.assert_not_called()

    def test_filters_by_source_type(self, mock_update, team):
        pg_source = _create_source(team, source_type="Postgres")
        mysql_source = _create_source(team, source_type="MySQL")
        pg_schema = _create_schema(pg_source, name="pg_table", should_sync=False, latest_error="connection is insecure")
        _create_schema(mysql_source, name="mysql_table", should_sync=False, latest_error="connection is insecure")

        call_command("reenable_schemas_by_error", "connection is insecure", source_type="Postgres", live_run=True)

        mock_update.assert_called_once_with(schema_id=str(pg_schema.id), team_id=team.id, should_sync=True)

    def test_reenables_across_teams(self, mock_update, team, team_2):
        source_1 = _create_source(team)
        source_2 = _create_source(team_2)
        _create_schema(source_1, name="t1", should_sync=False, latest_error="connection is insecure")
        _create_schema(source_2, name="t2", should_sync=False, latest_error="connection is insecure")

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        assert mock_update.call_count == 2

    def test_no_matches_prints_warning(self, mock_update, team, capsys):
        call_command("reenable_schemas_by_error", "nonexistent error string", live_run=True)

        mock_update.assert_not_called()
        captured = capsys.readouterr()
        assert "No disabled schemas found" in captured.out

    def test_continues_on_individual_failure(self, mock_update, team):
        source = _create_source(team)
        _create_schema(source, name="t1", should_sync=False, latest_error="connection is insecure")
        _create_schema(source, name="t2", should_sync=False, latest_error="connection is insecure")

        mock_update.side_effect = [Exception("temporal down"), None]

        call_command("reenable_schemas_by_error", "connection is insecure", live_run=True)

        assert mock_update.call_count == 2

    @pytest.mark.parametrize(
        "disabled_after,disabled_before,expected_name",
        [
            ("2026-04-17T00:00:00+00:00", None, "new"),
            (None, "2026-04-16T00:00:00+00:00", "old"),
            ("2026-04-16T17:00:00+00:00", "2026-04-17T00:00:00+00:00", "during"),
        ],
    )
    def test_date_filters(self, mock_update, team, disabled_after, disabled_before, expected_name):
        source = _create_source(team)
        old = _create_schema(source, name="old", should_sync=False, latest_error="connection is insecure")
        during = _create_schema(source, name="during", should_sync=False, latest_error="connection is insecure")
        new = _create_schema(source, name="new", should_sync=False, latest_error="connection is insecure")

        ExternalDataSchema.objects.filter(id=old.id).update(updated_at=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC))
        ExternalDataSchema.objects.filter(id=during.id).update(updated_at=datetime(2026, 4, 16, 20, 0, 0, tzinfo=UTC))
        ExternalDataSchema.objects.filter(id=new.id).update(updated_at=datetime(2026, 4, 18, 0, 0, 0, tzinfo=UTC))

        expected_schema = {"old": old, "during": during, "new": new}[expected_name]

        kwargs: dict = {"live_run": True}
        if disabled_after:
            kwargs["disabled_after"] = disabled_after
        if disabled_before:
            kwargs["disabled_before"] = disabled_before

        call_command("reenable_schemas_by_error", "connection is insecure", **kwargs)

        mock_update.assert_called_once_with(schema_id=str(expected_schema.id), team_id=team.id, should_sync=True)
