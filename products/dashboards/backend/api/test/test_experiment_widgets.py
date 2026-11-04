from concurrent.futures import Future
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.dashboards.backend.constants import DEFAULT_WIDGET_LIST_LIMIT
from products.dashboards.backend.widget_registry import (
    EXPERIMENT_RESULTS_WIDGET_TYPE,
    EXPERIMENTS_LIST_WIDGET_TYPE,
    validate_widget_config,
)
from products.dashboards.backend.widgets.experiment_results import run_experiment_results_widget
from products.dashboards.backend.widgets.experiments_list import run_experiments_list_widget
from products.experiments.backend.facade.contracts import (
    ExperimentResultsWidget,
    ExperimentResultsWidgetMetric,
    ExperimentResultsWidgetMetrics,
)
from products.experiments.backend.facade.testing import create_experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _block_experiment_for_member(team: Team, experiment_id: int, member: User) -> None:
    from products.access_control.backend.models.access_control import AccessControl  # noqa: PLC0415

    team.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
    team.organization.save()
    membership = OrganizationMembership.objects.get(organization=team.organization, user=member)
    AccessControl.objects.create(
        team=team,
        resource="experiment",
        resource_id=str(experiment_id),
        organization_member=membership,
        access_level="none",
    )


def _experiment_metric(uuid: str, name: str) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": uuid,
        "name": name,
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }


class TestExperimentWidgetConfigs(SimpleTestCase):
    def test_experiments_list_config_defaults(self) -> None:
        validated = validate_widget_config(EXPERIMENTS_LIST_WIDGET_TYPE, {})
        assert validated["limit"] == DEFAULT_WIDGET_LIST_LIMIT
        assert validated["status"] == "all"
        assert validated.get("createdBy") is None

    def test_experiment_results_config_defaults_to_unconfigured(self) -> None:
        validated = validate_widget_config(EXPERIMENT_RESULTS_WIDGET_TYPE, {})
        assert validated.get("experimentId") is None

    @parameterized.expand(
        [
            ("invalid_status", EXPERIMENTS_LIST_WIDGET_TYPE, {"status": "archived"}),
            ("high_limit", EXPERIMENTS_LIST_WIDGET_TYPE, {"limit": 100}),
            ("unknown_key", EXPERIMENTS_LIST_WIDGET_TYPE, {"evil": True}),
            ("non_int_experiment", EXPERIMENT_RESULTS_WIDGET_TYPE, {"experimentId": "abc"}),
            ("unknown_key_results", EXPERIMENT_RESULTS_WIDGET_TYPE, {"evil": True}),
        ]
    )
    def test_rejects_invalid_config(self, _label: str, widget_type: str, config: dict[str, Any]) -> None:
        with self.assertRaises(Exception):
            validate_widget_config(widget_type, config)


class TestExperimentsListWidget(APIBaseTest):
    def _create_experiment(
        self,
        name: str,
        *,
        created_by: User | None = None,
        start_date: Any = None,
        end_date: Any = None,
        flag_active: bool = True,
        deleted: bool = False,
    ) -> int:
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{name}",
            created_by=created_by or self.user,
            active=flag_active,
        )
        return create_experiment(
            team_id=self.team.id,
            name=name,
            feature_flag_id=feature_flag.id,
            created_by_id=(created_by or self.user).id,
            start_date=start_date,
            end_date=end_date,
            deleted=deleted,
        )

    def test_lists_experiments_with_serialized_rows(self) -> None:
        experiment_id = self._create_experiment("Running test", start_date=timezone.now())

        result = run_experiments_list_widget(self.team, {}, user=self.user)

        assert result["totalCount"] == 1
        assert result["hasMore"] is False
        row = result["results"][0]
        assert row["id"] == experiment_id
        assert row["name"] == "Running test"
        assert row["status"] == "running"
        assert row["feature_flag_key"] == "flag-Running test"
        assert row["created_by"]["email"] == self.user.email

    @parameterized.expand(
        [
            ("draft", "draft"),
            ("running", "running"),
            ("paused", "paused"),
            ("stopped", "stopped"),
        ]
    )
    def test_filters_by_status(self, _label: str, status_filter: str) -> None:
        now = timezone.now()
        expected_names = {
            "draft": "Draft exp",
            "running": "Running exp",
            "paused": "Paused exp",
            "stopped": "Stopped exp",
        }
        self._create_experiment("Draft exp")
        self._create_experiment("Running exp", start_date=now)
        self._create_experiment("Paused exp", start_date=now, flag_active=False)
        self._create_experiment("Stopped exp", start_date=now, end_date=now)

        result = run_experiments_list_widget(self.team, {"status": status_filter}, user=self.user)

        assert [row["name"] for row in result["results"]] == [expected_names[status_filter]]
        assert result["results"][0]["status"] == status_filter

    def test_filters_by_creator(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other-creator@posthog.com", None)
        self._create_experiment("Mine")
        self._create_experiment("Theirs", created_by=other_user)

        result = run_experiments_list_widget(self.team, {"createdBy": other_user.id}, user=self.user)

        assert [row["name"] for row in result["results"]] == ["Theirs"]

    def test_excludes_deleted_and_other_team_experiments(self) -> None:
        self._create_experiment("Deleted", deleted=True)
        self._create_experiment("Kept")

        result = run_experiments_list_widget(self.team, {}, user=self.user)

        assert [row["name"] for row in result["results"]] == ["Kept"]

    def test_caps_results_at_limit_and_reports_has_more(self) -> None:
        for index in range(3):
            self._create_experiment(f"Experiment {index}")

        result = run_experiments_list_widget(self.team, {"limit": 2}, user=self.user)

        assert len(result["results"]) == 2
        assert result["totalCount"] == 3
        assert result["hasMore"] is True

    def test_excludes_experiments_the_user_cannot_access(self) -> None:
        visible_id = self._create_experiment("Visible")
        blocked_id = self._create_experiment("Blocked")
        member = User.objects.create_and_join(self.organization, "member@example.test", "pw")
        _block_experiment_for_member(self.team, blocked_id, member)

        result = run_experiments_list_widget(self.team, {}, user=member)

        assert {row["name"] for row in result["results"]} == {"Visible"}
        assert visible_id in {row["id"] for row in result["results"]}


class TestExperimentResultsWidget(APIBaseTest):
    def _create_experiment(
        self,
        name: str = "Results test",
        *,
        team: Team | None = None,
        start_date: Any = None,
        metrics: list[dict[str, Any]] | None = None,
    ) -> int:
        team = team or self.team
        feature_flag = FeatureFlag.objects.create(team=team, key=f"flag-{name}", created_by=self.user)
        return create_experiment(
            team_id=team.id,
            name=name,
            feature_flag_id=feature_flag.id,
            created_by_id=self.user.id,
            start_date=start_date,
            metrics=metrics or [],
        )

    def test_returns_needs_configuration_when_no_experiment_selected(self) -> None:
        result = run_experiment_results_widget(self.team, {}, user=self.user)

        assert result == {
            "experiment": None,
            "metrics": [],
            "needsConfiguration": True,
            "hasExperiments": False,
        }

    def test_needs_configuration_reports_existing_experiments(self) -> None:
        self._create_experiment(name="Some experiment")
        result = run_experiment_results_widget(self.team, {}, user=self.user)

        assert result["needsConfiguration"] is True
        assert result["hasExperiments"] is True

    def test_returns_not_found_for_missing_experiment(self) -> None:
        result = run_experiment_results_widget(self.team, {"experimentId": 999999}, user=self.user)

        assert result == {"experiment": None, "metrics": [], "experimentNotFound": True}

    def test_returns_not_found_for_other_team_experiment(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        experiment_id = self._create_experiment("Other team", team=other_team)

        result = run_experiment_results_widget(self.team, {"experimentId": experiment_id}, user=self.user)

        assert result == {"experiment": None, "metrics": [], "experimentNotFound": True}

    def test_returns_not_found_for_experiment_the_user_cannot_access(self) -> None:
        experiment_id = self._create_experiment(start_date=timezone.now())
        member = User.objects.create_and_join(self.organization, "member@example.test", "pw")
        _block_experiment_for_member(self.team, experiment_id, member)

        result = run_experiment_results_widget(self.team, {"experimentId": experiment_id}, user=member)

        assert result == {"experiment": None, "metrics": [], "experimentNotFound": True}

    def test_draft_experiment_returns_summary_without_metrics(self) -> None:
        experiment_id = self._create_experiment(metrics=[_experiment_metric("uuid-1", "Mean metric")])

        result = run_experiment_results_widget(self.team, {"experimentId": experiment_id}, user=self.user)

        assert result["experiment"]["id"] == experiment_id
        assert result["experiment"]["status"] == "draft"
        assert result["metrics"] == []
        assert result["secondaryMetrics"] == []
        assert "totalMetricsCount" not in result
        assert "totalSecondaryMetricsCount" not in result

    @parameterized.expand([("with_total_count", True), ("without_total_count", False)])
    def test_serializes_the_computed_metrics(self, _label: str, include_total_count: bool) -> None:
        start_date = timezone.now()
        computed = ExperimentResultsWidgetMetric(
            uuid="uuid-1",
            name="Mean metric",
            metric={"metric_type": "mean"},
            result={"baseline": {"key": "control"}},
            error=None,
        )
        failed = ExperimentResultsWidgetMetric(
            uuid="secondary-1", name="Broken metric", metric=None, result=None, error="Could not compute."
        )
        widget = ExperimentResultsWidget(
            id=7,
            name="Results test",
            status="running",
            start_date=start_date,
            end_date=None,
            feature_flag_key="flag-results",
            metrics=ExperimentResultsWidgetMetrics(
                primary=(computed,), secondary=(failed,), primary_total=4, secondary_total=1
            ),
        )

        with patch(
            "products.dashboards.backend.widgets.experiment_results.experiment_results_widget", return_value=widget
        ):
            result = run_experiment_results_widget(
                self.team, {"experimentId": 7}, user=self.user, include_total_count=include_total_count
            )

        assert result == {
            "experiment": {
                "id": 7,
                "name": "Results test",
                "status": "running",
                "start_date": start_date.isoformat(),
                "end_date": None,
                "feature_flag_key": "flag-results",
            },
            "metrics": [
                {
                    "uuid": "uuid-1",
                    "name": "Mean metric",
                    "metric": {"metric_type": "mean"},
                    "result": {"baseline": {"key": "control"}},
                    "error": None,
                }
            ],
            "secondaryMetrics": [
                {
                    "uuid": "secondary-1",
                    "name": "Broken metric",
                    "metric": None,
                    "result": None,
                    "error": "Could not compute.",
                }
            ],
            **({"totalMetricsCount": 4, "totalSecondaryMetricsCount": 1} if include_total_count else {}),
        }

    def test_legacy_metric_reports_unsupported_error(self) -> None:
        experiment_id = self._create_experiment(
            start_date=timezone.now(),
            metrics=[{"kind": "ExperimentTrendsQuery", "uuid": "uuid-legacy", "name": "Legacy"}],
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment_id}, user=self.user)

        entry = result["metrics"][0]
        assert entry["error"] == "Legacy metrics are not supported in this widget."
        assert entry["result"] is None


class _InlineExecutor:
    """Runs run_widgets work items on the test thread so widget queries can see
    data created inside the test transaction (real threads get new DB connections)."""

    def __init__(self, max_workers: int | None = None) -> None:
        pass

    def __enter__(self) -> "_InlineExecutor":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> "Future[Any]":
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class TestExperimentWidgetsViaRunWidgetsEndpoint(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.executor_patcher = patch(
            "products.dashboards.backend.api.dashboard.ThreadPoolExecutor",
            _InlineExecutor,
        )
        self.executor_patcher.start()

    def tearDown(self) -> None:
        self.executor_patcher.stop()
        super().tearDown()

    def _run(self, dashboard_id: int, tile_ids: list[int]) -> dict[str, Any]:
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": ",".join(str(tile_id) for tile_id in tile_ids)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_runs_experiments_list_widget_tile(self) -> None:
        feature_flag = FeatureFlag.objects.create(team=self.team, key="endpoint-flag", created_by=self.user)
        create_experiment(
            team_id=self.team.id,
            name="Endpoint experiment",
            feature_flag_id=feature_flag.id,
            created_by_id=self.user.id,
        )
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="experiments_list", config={"limit": 5}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        tile_result = body["results"][0]
        assert tile_result["widget_type"] == "experiments_list"
        assert tile_result["error"] is None
        assert tile_result["result"]["results"][0]["name"] == "Endpoint experiment"

    def test_runs_experiment_results_widget_tile_unconfigured(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="experiment_results", config={}
        )
        tile_id = dashboard_json["tiles"][0]["id"]

        body = self._run(dashboard_id, [tile_id])

        tile_result = body["results"][0]
        assert tile_result["widget_type"] == "experiment_results"
        assert tile_result["error"] is None
        assert tile_result["result"]["needsConfiguration"] is True
