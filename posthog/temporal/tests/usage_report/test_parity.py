"""Byte-compatibility parity tests between the legacy Celery serialization
chain and the new Temporal facade functions.

Both paths must produce *exactly* the same `full_report_dict` per
organization given the same `all_data` + Postgres state, otherwise
billing's parity validation will trip the moment we cut over.

The expensive gather queries (`get_teams_with_*`) aren't exercised — the
parity we care about is everything *after* `all_data` is materialized:
team aggregation, org rollup, full-report serialization. Both paths
already call the same private helpers under the hood, so this test
guards against drift if anyone refactors one chain without the other.
"""

import json
import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from posthog.models import Organization, Team
from posthog.tasks.usage_report import (
    InstanceMetadata,
    _add_team_report_to_org_reports,
    _get_full_org_usage_report,
    _get_full_org_usage_report_as_dict,
    _get_team_report,
    _get_teams_for_usage_reports,
    build_org_reports,
    serialize_full_org_report,
)
from posthog.temporal.usage_report.aggregator import iter_chunk_lines
from posthog.temporal.usage_report.queries import QUERIES


def _all_destination_keys() -> list[str]:
    """Every key `_get_team_report` reads, derived from the registry so we
    don't have to keep the test in sync with the spec list by hand.
    """
    keys: list[str] = []
    for spec in QUERIES:
        if spec.output == "multi":
            keys.extend(spec.multi_keys_mapping.values())
        else:
            keys.append(spec.name)
    return keys


def _instance_metadata() -> InstanceMetadata:
    return InstanceMetadata(
        deployment_infrastructure="test",
        realm="cloud",
        period={
            "start_inclusive": "2026-05-04T00:00:00+00:00",
            "end_inclusive": "2026-05-04T23:59:59.999999+00:00",
        },
        site_url="https://us.posthog.com",
        product="cloud",
        helm=None,
        clickhouse_version=None,
        users_who_logged_in=None,
        users_who_logged_in_count=None,
        users_who_signed_up=None,
        users_who_signed_up_count=None,
        table_sizes=None,
        plugins_installed=None,
        plugins_enabled=None,
        instance_tag="test-tag",
    )


def _seed_all_data(team_a_id: int, team_b_id: int, team_c_id: int) -> dict[str, dict[int, int]]:
    """A non-trivial `all_data` covering several destination keys.

    Realistic enough to prove the team→org rollup math is identical:
    different team distributions per metric, some teams missing from
    some metrics, and at least one org with multiple teams summed. All
    other destination keys (derived from the registry) get an empty
    dict so `_get_team_report`'s lookups don't KeyError.
    """
    interesting: dict[str, dict[int, int]] = {
        "teams_with_event_count_in_period": {team_a_id: 100, team_b_id: 50, team_c_id: 25},
        "teams_with_enhanced_persons_event_count_in_period": {team_a_id: 80, team_b_id: 40},
        "teams_with_recording_count_in_period": {team_a_id: 8, team_c_id: 3},
        "teams_with_recording_bytes_in_period": {team_a_id: 1_234_567, team_c_id: 89_012},
        "teams_with_decide_requests_count_in_period": {team_a_id: 1_000, team_b_id: 200, team_c_id: 50},
        "teams_with_local_evaluation_requests_count_in_period": {team_b_id: 5},
        "teams_with_dashboard_count": {team_a_id: 4, team_b_id: 2, team_c_id: 1},
        "teams_with_ff_count": {team_a_id: 7, team_b_id: 3},
        "teams_with_survey_count": {team_a_id: 1, team_c_id: 2},
        "teams_with_web_events_count_in_period": {team_a_id: 60, team_b_id: 30},
        "teams_with_exceptions_captured_in_period": {team_a_id: 5, team_b_id: 1},
        "teams_with_web_exceptions_captured_in_period": {team_a_id: 5},
        "teams_with_node_exceptions_captured_in_period": {team_b_id: 1},
        "teams_with_api_queries_count": {team_a_id: 10},
        "teams_with_api_queries_read_bytes": {team_a_id: 1_500_000},
    }
    return {key: interesting.get(key, {}) for key in _all_destination_keys()}


def _celery_serialize(team_a_id: int, team_b_id: int, team_c_id: int, period_start: datetime) -> dict[str, Any]:
    """Walk the same private helpers `send_all_org_usage_reports` uses,
    then serialize the same way `capture_report` / `_queue_report` see it.
    """
    all_data = _seed_all_data(team_a_id, team_b_id, team_c_id)
    instance_metadata = _instance_metadata()
    org_reports: dict[str, Any] = {}
    for team in _get_teams_for_usage_reports():
        team_report = _get_team_report(all_data, team)
        _add_team_report_to_org_reports(org_reports, team, team_report, period_start)
    return {
        org_id: _get_full_org_usage_report_as_dict(_get_full_org_usage_report(report, instance_metadata))
        for org_id, report in org_reports.items()
    }


def _temporal_serialize(team_a_id: int, team_b_id: int, team_c_id: int, period_start: datetime) -> dict[str, Any]:
    """Walk the public facade functions the Temporal aggregation activity
    uses (`build_org_reports` → `serialize_full_org_report`).
    """
    all_data = _seed_all_data(team_a_id, team_b_id, team_c_id)
    instance_metadata = _instance_metadata()
    org_reports = build_org_reports(all_data, period_start)
    return {org_id: serialize_full_org_report(report, instance_metadata) for org_id, report in org_reports.items()}


@pytest.mark.django_db
def test_serialization_parity_celery_vs_temporal() -> None:
    """The full per-org dict billing consumes must be identical between
    the Celery and Temporal paths for any given `all_data` snapshot.

    Two orgs × three teams (org_a has two teams so we exercise the
    multi-team rollup; org_b has one). If this drifts, billing's parity
    validation will explode — fix the divergent helper, not the test.
    """
    org_a = Organization.objects.create(name="Parity Org A")
    org_b = Organization.objects.create(name="Parity Org B")
    team_a1 = Team.objects.create(organization=org_a, name="A1")
    team_a2 = Team.objects.create(organization=org_a, name="A2")
    team_b = Team.objects.create(organization=org_b, name="B")

    period_start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)

    celery_dicts = _celery_serialize(team_a1.id, team_a2.id, team_b.id, period_start)
    temporal_dicts = _temporal_serialize(team_a1.id, team_a2.id, team_b.id, period_start)

    # Both paths must produce the same set of organizations.
    assert set(celery_dicts.keys()) == set(temporal_dicts.keys())

    # And the same dict per org — compare via JSON to fail loudly on any
    # drift (unhashable types, ordering of nested dicts, etc.).
    for org_id in celery_dicts:
        celery_json = json.dumps(celery_dicts[org_id], sort_keys=True, default=str)
        temporal_json = json.dumps(temporal_dicts[org_id], sort_keys=True, default=str)
        assert celery_json == temporal_json, (
            f"Drift between Celery and Temporal serialization for org {org_id}.\n"
            f"Celery diff:\n{celery_json[:500]}\n"
            f"Temporal diff:\n{temporal_json[:500]}"
        )

    # Sanity check: the rollup math is non-trivial — org_a has two teams,
    # so its event_count_in_period should be the sum.
    assert temporal_dicts[str(org_a.id)]["event_count_in_period"] == 100 + 50  # team_a1 + team_a2
    assert temporal_dicts[str(org_b.id)]["event_count_in_period"] == 25  # team_b only


@pytest.mark.django_db
def test_iter_chunk_lines_matches_celery_serialization() -> None:
    """The aggregation activity ends up writing JSONL lines via
    `iter_chunk_lines`. That function should yield the same per-org
    `usage_report` dict the Celery `_queue_report` would have built.

    The shared test DB may have pre-seeded orgs; we don't care how many
    rows come out, only that the row for *our* org matches between the
    two paths.
    """
    org = Organization.objects.create(name="Parity Iter Org")
    team = Team.objects.create(organization=org, name="Solo")

    period_start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
    all_data = _seed_all_data(team.id, team.id, team.id)
    instance_metadata = _instance_metadata()

    celery_dicts = _celery_serialize(team.id, team.id, team.id, period_start)

    org_reports = build_org_reports(all_data, period_start)
    assert str(org.id) in org_reports

    lines_by_org = {
        line["organization_id"]: (line, has_usage)
        for line, has_usage in iter_chunk_lines(org_reports.values(), instance_metadata)
    }
    assert str(org.id) in lines_by_org
    line, has_usage = lines_by_org[str(org.id)]
    assert has_usage is True
    assert line["usage_report"] == celery_dicts[str(org.id)]


@pytest.mark.django_db
def test_build_org_reports_matches_legacy_loop() -> None:
    """Spot-check that the public `build_org_reports` facade returns
    the same `OrgReport` dataclass the legacy in-line loop produced for
    a given org. Other orgs in the shared test DB are ignored.
    """
    org = Organization.objects.create(name="Facade Parity Org")
    team_1 = Team.objects.create(organization=org, name="One")
    team_2 = Team.objects.create(organization=org, name="Two")

    period_start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
    all_data = _seed_all_data(team_1.id, team_2.id, team_1.id)

    legacy: dict[str, Any] = {}
    for team in _get_teams_for_usage_reports():
        team_report = _get_team_report(all_data, team)
        _add_team_report_to_org_reports(legacy, team, team_report, period_start)

    facade = build_org_reports(all_data, period_start)

    assert str(org.id) in legacy
    assert str(org.id) in facade
    assert dataclasses.asdict(legacy[str(org.id)]) == dataclasses.asdict(facade[str(org.id)])
