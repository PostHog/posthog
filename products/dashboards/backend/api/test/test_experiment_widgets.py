from concurrent.futures import Future
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

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
from products.dashboards.backend.widgets.experiment_results import (
    MAX_EXPERIMENT_RESULTS_WIDGET_METRICS,
    run_experiment_results_widget,
)
from products.dashboards.backend.widgets.experiments_list import run_experiments_list_widget
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _block_experiment_for_member(team: Team, experiment: Experiment, member: User) -> None:
    from ee.models.rbac.access_control import AccessControl  # noqa: PLC0415

    team.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
    team.organization.save()
    membership = OrganizationMembership.objects.get(organization=team.organization, user=member)
    AccessControl.objects.create(
        team=team,
        resource="experiment",
        resource_id=str(experiment.id),
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


class TestExperimentWidgetConfigs(APIBaseTest):
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
    ) -> Experiment:
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{name}",
            created_by=created_by or self.user,
            active=flag_active,
        )
        return Experiment.objects.create(
            team=self.team,
            name=name,
            feature_flag=feature_flag,
            created_by=created_by or self.user,
            start_date=start_date,
            end_date=end_date,
        )

    def test_lists_experiments_with_serialized_rows(self) -> None:
        experiment = self._create_experiment("Running test", start_date=timezone.now())

        result = run_experiments_list_widget(self.team, {}, user=self.user)

        assert result["totalCount"] == 1
        assert result["hasMore"] is False
        row = result["results"][0]
        assert row["id"] == experiment.id
        assert row["name"] == "Running test"
        assert row["status"] == "running"
        assert row["feature_flag_key"] == experiment.feature_flag.key
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
        deleted = self._create_experiment("Deleted")
        deleted.deleted = True
        deleted.save()
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
        visible = self._create_experiment("Visible")
        blocked = self._create_experiment("Blocked")
        member = User.objects.create_and_join(self.organization, "member@example.test", "pw")
        _block_experiment_for_member(self.team, blocked, member)

        result = run_experiments_list_widget(self.team, {}, user=member)

        assert {row["name"] for row in result["results"]} == {"Visible"}
        assert visible.id in {row["id"] for row in result["results"]}


class TestExperimentResultsWidget(APIBaseTest):
    def _create_experiment(
        self,
        name: str = "Results test",
        *,
        start_date: Any = None,
        metrics: list[dict[str, Any]] | None = None,
        metrics_secondary: list[dict[str, Any]] | None = None,
    ) -> Experiment:
        feature_flag = FeatureFlag.objects.create(team=self.team, key=f"flag-{name}", created_by=self.user)
        return Experiment.objects.create(
            team=self.team,
            name=name,
            feature_flag=feature_flag,
            created_by=self.user,
            start_date=start_date,
            metrics=metrics or [],
            metrics_secondary=metrics_secondary or [],
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
        flag = FeatureFlag.objects.create(team=other_team, key="other-flag", created_by=self.user)
        experiment = Experiment.objects.create(
            team=other_team, name="Other team", feature_flag=flag, created_by=self.user
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result == {"experiment": None, "metrics": [], "experimentNotFound": True}

    def test_returns_not_found_for_experiment_the_user_cannot_access(self) -> None:
        experiment = self._create_experiment(start_date=timezone.now())
        member = User.objects.create_and_join(self.organization, "member@example.test", "pw")
        _block_experiment_for_member(self.team, experiment, member)

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=member)

        assert result == {"experiment": None, "metrics": [], "experimentNotFound": True}

    def test_draft_experiment_returns_summary_without_metrics(self) -> None:
        experiment = self._create_experiment(metrics=[_experiment_metric("uuid-1", "Mean metric")])

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result["experiment"]["id"] == experiment.id
        assert result["experiment"]["status"] == "draft"
        assert result["metrics"] == []
        assert result["secondaryMetrics"] == []
        assert "totalMetricsCount" not in result
        assert "totalSecondaryMetricsCount" not in result

    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_computes_results_for_primary_metrics(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(
            model_dump=lambda mode="json": {
                "kind": "NewExperimentQueryResponse",
                "baseline": {"key": "control", "number_of_samples": 100, "sum": 40, "sum_squares": 30},
                "variant_results": [{"key": "test", "number_of_samples": 100, "sum": 55, "sum_squares": 40}],
                "clickhouse_sql": "SELECT secret",
            }
        )
        experiment = self._create_experiment(
            start_date=timezone.now(),
            metrics=[_experiment_metric("uuid-1", "Mean metric")],
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result["experiment"]["status"] == "running"
        assert result["totalMetricsCount"] == 1
        entry = result["metrics"][0]
        assert entry["name"] == "Mean metric"
        assert entry["error"] is None
        assert entry["metric"]["metric_type"] == "mean"
        assert entry["result"]["baseline"]["key"] == "control"
        assert "clickhouse_sql" not in entry["result"]
        query = mock_runner_cls.call_args.kwargs["query"]
        assert query.experiment_id == experiment.id

    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_computes_results_for_secondary_metrics(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(
            model_dump=lambda mode="json": {
                "kind": "NewExperimentQueryResponse",
                "baseline": {"key": "control", "number_of_samples": 100, "sum": 40, "sum_squares": 30},
                "variant_results": [{"key": "test", "number_of_samples": 100, "sum": 55, "sum_squares": 40}],
            }
        )
        experiment = self._create_experiment(
            start_date=timezone.now(),
            metrics_secondary=[_experiment_metric("secondary-1", "Revenue per user")],
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result["metrics"] == []
        assert result["totalMetricsCount"] == 0
        assert result["totalSecondaryMetricsCount"] == 1
        entry = result["secondaryMetrics"][0]
        assert entry["name"] == "Revenue per user"
        assert entry["error"] is None
        assert entry["result"]["baseline"]["key"] == "control"

    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_computes_both_primary_and_secondary_metrics(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(model_dump=lambda mode="json": {})
        experiment = self._create_experiment(
            start_date=timezone.now(),
            metrics=[_experiment_metric("uuid-1", "Primary metric")],
            metrics_secondary=[_experiment_metric("secondary-1", "Secondary metric")],
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert [entry["name"] for entry in result["metrics"]] == ["Primary metric"]
        assert [entry["name"] for entry in result["secondaryMetrics"]] == ["Secondary metric"]
        assert mock_runner_cls.return_value.run.call_count == 2

    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_caps_computed_secondary_metrics_and_reports_total(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(model_dump=lambda mode="json": {})
        metrics_secondary = [
            _experiment_metric(f"secondary-{index}", f"Secondary {index}")
            for index in range(MAX_EXPERIMENT_RESULTS_WIDGET_METRICS + 2)
        ]
        experiment = self._create_experiment(start_date=timezone.now(), metrics_secondary=metrics_secondary)

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result["totalSecondaryMetricsCount"] == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS + 2
        assert len(result["secondaryMetrics"]) == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS
        assert mock_runner_cls.return_value.run.call_count == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS

    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_caps_computed_metrics_and_reports_total(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(model_dump=lambda mode="json": {})
        metrics = [
            _experiment_metric(f"uuid-{index}", f"Metric {index}")
            for index in range(MAX_EXPERIMENT_RESULTS_WIDGET_METRICS + 2)
        ]
        experiment = self._create_experiment(start_date=timezone.now(), metrics=metrics)

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result["totalMetricsCount"] == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS + 2
        assert len(result["metrics"]) == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS
        assert mock_runner_cls.return_value.run.call_count == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS

    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_caps_primary_and_secondary_independently(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(model_dump=lambda mode="json": {})
        over_cap = MAX_EXPERIMENT_RESULTS_WIDGET_METRICS + 2
        experiment = self._create_experiment(
            start_date=timezone.now(),
            metrics=[_experiment_metric(f"uuid-{index}", f"Metric {index}") for index in range(over_cap)],
            metrics_secondary=[
                _experiment_metric(f"secondary-{index}", f"Secondary {index}") for index in range(over_cap)
            ],
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        assert result["totalMetricsCount"] == over_cap
        assert result["totalSecondaryMetricsCount"] == over_cap
        assert len(result["metrics"]) == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS
        assert len(result["secondaryMetrics"]) == MAX_EXPERIMENT_RESULTS_WIDGET_METRICS
        # The cap is per-section, so a fully-loaded widget runs at most 2x the constant.
        assert mock_runner_cls.return_value.run.call_count == 2 * MAX_EXPERIMENT_RESULTS_WIDGET_METRICS

    def test_legacy_metric_reports_unsupported_error(self) -> None:
        experiment = self._create_experiment(
            start_date=timezone.now(),
            metrics=[{"kind": "ExperimentTrendsQuery", "uuid": "uuid-legacy", "name": "Legacy"}],
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        entry = result["metrics"][0]
        assert entry["error"] == "Legacy metrics are not supported in this widget."
        assert entry["result"] is None

    @parameterized.expand(
        [
            ("primary", "metrics"),
            ("secondary", "secondaryMetrics"),
        ]
    )
    @patch("products.dashboards.backend.widgets.experiment_results.ExperimentQueryRunner")
    def test_metric_failure_is_isolated_and_sanitized(
        self, _label: str, result_key: str, mock_runner_cls: MagicMock
    ) -> None:
        mock_runner_cls.return_value.run.side_effect = Exception("SELECT * FROM secret_table")
        broken = [_experiment_metric("uuid-1", "Broken metric")]
        is_primary = result_key == "metrics"
        experiment = self._create_experiment(
            start_date=timezone.now(),
            metrics=broken if is_primary else None,
            metrics_secondary=None if is_primary else broken,
        )

        result = run_experiment_results_widget(self.team, {"experimentId": experiment.id}, user=self.user)

        entry = result[result_key][0]
        assert entry["error"] == "Could not compute results for this metric."
        assert "secret_table" not in str(entry)


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
        self.widgets_flag_patcher = patch(
            "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
            return_value=True,
        )
        self.widget_create_flag_patcher = patch(
            "products.dashboards.backend.widget_create.dashboard_widgets_enabled",
            return_value=True,
        )
        self.widgets_flag_patcher.start()
        self.widget_create_flag_patcher.start()

    def tearDown(self) -> None:
        self.executor_patcher.stop()
        self.widget_create_flag_patcher.stop()
        self.widgets_flag_patcher.stop()
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
        Experiment.objects.create(
            team=self.team, name="Endpoint experiment", feature_flag=feature_flag, created_by=self.user
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
