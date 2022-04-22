from unittest import mock

import pytest
from django.conf import settings
from pytest_mock.plugin import MockerFixture

from posthog.internal_metrics import gauge, incr, timing
from posthog.internal_metrics.team import (
    CLICKHOUSE_DASHBOARD,
    NAME,
    get_internal_metrics_dashboards,
    get_internal_metrics_team_id,
)
from posthog.models import Team
from posthog.models.dashboard import Dashboard


@pytest.fixture(autouse=True)
def mock_capture_internal(mocker: MockerFixture):
    get_internal_metrics_team_id.cache_clear()
    mocker.patch.object(settings, "CAPTURE_INTERNAL_METRICS", True)
    mocker.patch("posthog.utils.get_machine_id", return_value="machine_id")
    yield mocker.patch("posthog.api.capture.capture_internal")

    mocker.patch.object(settings, "CAPTURE_INTERNAL_METRICS", False)
    get_internal_metrics_team_id.cache_clear()


def test_methods_capture_enabled(db, mock_capture_internal):
    timing("foo_metric", 100, tags={"team_id": 15})
    gauge("bar_metric", 20, tags={"team_id": 15})
    incr("zeta_metric")

    mock_capture_internal.assert_any_call(
        {"event": "$$foo_metric", "properties": {"value": 100, "team_id": 15}},
        "machine_id",
        None,
        None,
        mock.ANY,
        mock.ANY,
        get_internal_metrics_team_id(),
    )

    mock_capture_internal.assert_any_call(
        {"event": "$$bar_metric", "properties": {"value": 20, "team_id": 15}},
        "machine_id",
        None,
        None,
        mock.ANY,
        mock.ANY,
        get_internal_metrics_team_id(),
    )

    mock_capture_internal.assert_any_call(
        {"event": "$$zeta_metric", "properties": {"value": 1}},
        "machine_id",
        None,
        None,
        mock.ANY,
        mock.ANY,
        get_internal_metrics_team_id(),
    )


def test_methods_capture_disabled(db, mock_capture_internal, mocker: MockerFixture):
    mocker.patch.object(settings, "CAPTURE_INTERNAL_METRICS", False)

    timing("foo_metric", 100, tags={"team_id": 15})
    gauge("bar_metric", 20, tags={"team_id": 15})
    incr("zeta_metric")

    mock_capture_internal.assert_not_called()


def test_get_internal_metrics_team_id_with_capture_disabled(db, django_assert_num_queries, mocker: MockerFixture):
    mocker.patch.object(settings, "CAPTURE_INTERNAL_METRICS", False)

    with django_assert_num_queries(0):
        assert get_internal_metrics_team_id() is None


def test_get_internal_team_id_returns_a_team_id_and_memoizes(db, django_assert_num_queries):
    team_id = get_internal_metrics_team_id()
    assert isinstance(team_id, int)

    with django_assert_num_queries(0):
        assert get_internal_metrics_team_id() == team_id

    team = Team.objects.get(pk=team_id)
    assert team.name == NAME
    assert team.organization.name == NAME
    assert team.organization.for_internal_metrics


def test_get_internal_metrics_dashboards(db):
    info = get_internal_metrics_dashboards()

    team = Team.objects.get(pk=get_internal_metrics_team_id())
    dashboard = Dashboard.objects.get(pk=info["clickhouse"]["id"])

    assert Dashboard.objects.count() == 1
    assert dashboard.team_id == team.pk
    assert dashboard.name == CLICKHOUSE_DASHBOARD["name"]
    assert dashboard.insights.count() == len(CLICKHOUSE_DASHBOARD["items"])

    assert get_internal_metrics_dashboards() == info


def test_dashboard_gets_regenerated_when_info_changes(db, mocker):
    info = get_internal_metrics_dashboards()

    mocker.patch.dict(CLICKHOUSE_DASHBOARD, {"some": "change"})

    new_info = get_internal_metrics_dashboards()
    assert new_info != info
    assert Dashboard.objects.count() == 1
