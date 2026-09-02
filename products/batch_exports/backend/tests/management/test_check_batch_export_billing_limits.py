import json
import datetime as dt
from io import StringIO

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, add_limited_team_tokens

pytestmark = [
    pytest.mark.django_db,
]


@pytest.fixture
def organization():
    return create_organization("test-billing-limits")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


def _create_batch_export(team, destination_type="S3", paused=False, deleted=False):
    destination = BatchExportDestination.objects.create(type=destination_type, config={})
    return BatchExport.objects.create(
        name=f"{destination_type}-export",
        team=team,
        destination=destination,
        interval="hour",
        paused=paused,
        deleted=deleted,
    )


def _limit_team(team, expired=False):
    delta = dt.timedelta(days=-1) if expired else dt.timedelta(days=1)
    score = int((dt.datetime.now(dt.UTC) + delta).timestamp())
    add_limited_team_tokens(
        QuotaResource.ROWS_EXPORTED,
        {team.api_token: score},
        QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
    )


def _call_command(*args):
    stdout = StringIO()
    call_command("check_batch_export_billing_limits", *args, stdout=stdout)
    return stdout.getvalue()


def _parse_json_output(output):
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


@pytest.mark.parametrize(
    "limited,expired,expected_over_limit",
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
    ],
)
def test_team_id_reports_over_limit(organization, team, limited, expired, expected_over_limit):
    """Test the command runs the production predicate against the quota-limit zset.

    An expired zset entry must not report a team as over limit.
    """
    organization.usage = {"rows_exported": {"usage": 500, "todays_usage": 100, "limit": 300}}
    organization.save()
    if limited:
        _limit_team(team, expired=expired)

    reports = _parse_json_output(_call_command("--team-id", str(team.id), "--json"))

    assert len(reports) == 1
    report = reports[0]
    assert report["team_id"] == team.id
    assert report["over_billing_limit"] is expected_over_limit
    assert report["usage"] == 500
    assert report["todays_usage"] == 100
    assert report["limit"] == 300


def test_fleet_audit_lists_only_limited_teams_with_active_billable_exports(organization):
    """Test the fleet audit's filters.

    Only teams in the quota-limit zset with at least one non-deleted, non-paused
    export to a billable destination should be listed.
    """
    team_billable = create_team(organization=organization)
    _create_batch_export(team_billable)
    _limit_team(team_billable)

    team_http_only = create_team(organization=organization)
    _create_batch_export(team_http_only, destination_type="HTTP")
    _limit_team(team_http_only)

    team_workflows_only = create_team(organization=organization)
    _create_batch_export(team_workflows_only, destination_type="Workflows")
    _limit_team(team_workflows_only)

    team_paused = create_team(organization=organization)
    _create_batch_export(team_paused, paused=True)
    _limit_team(team_paused)

    team_deleted = create_team(organization=organization)
    _create_batch_export(team_deleted, deleted=True)
    _limit_team(team_deleted)

    team_not_limited = create_team(organization=organization)
    _create_batch_export(team_not_limited)

    reports = _parse_json_output(_call_command("--json"))

    assert [report["team_id"] for report in reports] == [team_billable.id]
    assert reports[0]["over_billing_limit"] is True
    assert reports[0]["active_billable_exports"] == ["S3"]


def test_organization_id_reports_all_teams(organization):
    team_limited = create_team(organization=organization)
    _create_batch_export(team_limited)
    _limit_team(team_limited)

    team_not_limited = create_team(organization=organization)

    reports = _parse_json_output(_call_command("--organization-id", str(organization.id), "--json"))

    over_limit_by_team = {report["team_id"]: report["over_billing_limit"] for report in reports}
    assert over_limit_by_team == {team_limited.id: True, team_not_limited.id: False}


def test_unknown_organization_raises():
    with pytest.raises(CommandError):
        _call_command("--organization-id", "019fb3d0-0000-0000-0000-000000000000")
