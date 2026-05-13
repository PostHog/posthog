"""Tests for the preflight validation logic.

These exercise the structural checks fully and stub HogQL execution for the
data-touching paths. End-to-end validation against real Hedgebox data lives in
``test_api.py``'s presentation tests (which run inside the Django stack and use
the team scope set by conftest).
"""

from typing import Any

import pytest
from unittest.mock import patch

from products.automl.backend import logic
from products.automl.backend.facade import contracts
from products.automl.backend.facade.enums import AutonomyLevel, Cadence, TaskType


def _classification_params(**overrides: Any) -> contracts.CreatePipelineInput:
    """Build a classification CreatePipelineInput with sensible defaults.

    Tests override individual fields to exercise specific paths. Keeps each
    test focused on the one thing it's asserting.
    """
    base: dict[str, Any] = {
        "name": "cls_test",
        "task_type": TaskType.CLASSIFICATION,
        "config": {"target_event": "uploaded_file", "horizon_days": 14, "framing": "adoption"},
        "training_population": {"kind": "hogql", "query": "SELECT person_id FROM events"},
        "inference_population": {"kind": "hogql", "query": "SELECT person_id FROM events"},
        "description": "",
        "autonomy": AutonomyLevel.CHAMPION_ONLY,
        "inference_cadence": Cadence.DAILY,
        "retraining_cadence": Cadence.DAILY,
        "output_property_name": "automl_p_uploaded_file_14d",
    }
    base.update(overrides)
    return contracts.CreatePipelineInput(**base)


def _stub_hogql_results(rows: list[int]) -> Any:
    """Build a fake HogQLQueryResponse-shaped object whose ``.results`` matches the layout the validator reads."""

    class _Stub:
        results = [[row] for row in rows]

    return _Stub()


def _codes(findings: list[contracts.ValidationFinding]) -> set[str]:
    return {f.code for f in findings}


@pytest.mark.django_db
def test_classification_happy_path_passes(team):
    """A well-formed classification config with healthy data produces ok=True."""
    # Three count queries fire in this path: training, inference, recent positives.
    # 50k training rows, 30k inference rows, 1500 positives -> 3% base rate, passes the floor.
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([50_000]), _stub_hogql_results([30_000]), _stub_hogql_results([1_500])],
    ):
        report = logic.run_validation(team_id=team.id, params=_classification_params())

    assert report.ok is True
    assert report.summary.estimated_training_rows == 50_000
    assert report.summary.estimated_inference_rows == 30_000
    assert report.summary.estimated_positive_count == 1_500
    assert report.summary.estimated_positive_rate == pytest.approx(0.03)
    assert report.summary.target_event == "uploaded_file"
    # No block findings emitted.
    assert not any(f.severity is contracts.ValidationSeverity.BLOCK for f in report.findings)


@pytest.mark.django_db
def test_classification_low_volume_blocks(team):
    """Training volume under 5k entities blocks pipeline creation."""
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([2_500]), _stub_hogql_results([1_000]), _stub_hogql_results([200])],
    ):
        report = logic.run_validation(team_id=team.id, params=_classification_params())

    assert report.ok is False
    assert "training_volume_too_low" in _codes(report.findings)


@pytest.mark.django_db
def test_classification_low_base_rate_blocks(team):
    """A positive base rate under 0.5% blocks even when volume is healthy."""
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[
            _stub_hogql_results([100_000]),  # training
            _stub_hogql_results([50_000]),  # inference
            _stub_hogql_results([200]),  # positives — 0.2% base rate
        ],
    ):
        report = logic.run_validation(team_id=team.id, params=_classification_params())

    assert report.ok is False
    assert "positive_rate_too_low" in _codes(report.findings)


@pytest.mark.django_db
def test_classification_missing_required_keys_blocks(team):
    """Classification without target_event and horizon_days is rejected at structural level."""
    # No HogQL execution should happen — the population checks still run, but the
    # patch makes count queries return safe defaults so we isolate the structural finding.
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([1_000])],
    ):
        report = logic.run_validation(
            team_id=team.id,
            params=_classification_params(config={}),
        )

    assert report.ok is False
    assert "config_missing_required_keys" in _codes(report.findings)


@pytest.mark.django_db
def test_inference_volume_warns_when_high(team):
    """A 7-figure-events-per-day projection trips the warn threshold."""
    # 250k inference rows at hourly cadence -> 6M events/day, way over the 200k ceiling.
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([100_000]), _stub_hogql_results([250_000]), _stub_hogql_results([5_000])],
    ):
        report = logic.run_validation(
            team_id=team.id,
            params=_classification_params(inference_cadence=Cadence.HOURLY),
        )

    assert "inference_volume_high" in _codes(report.findings)


@pytest.mark.django_db
def test_output_property_must_not_use_dollar_prefix(team):
    """Reserved $ prefix blocks regardless of task type."""
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([1_000]), _stub_hogql_results([300])],
    ):
        report = logic.run_validation(
            team_id=team.id,
            params=_classification_params(output_property_name="$reserved_name"),
        )

    assert report.ok is False
    assert "output_property_reserved_prefix" in _codes(report.findings)


@pytest.mark.django_db
def test_output_property_unprefixed_warns(team):
    """Property names without the automl_ prefix warn but don't block."""
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([1_000]), _stub_hogql_results([300])],
    ):
        report = logic.run_validation(
            team_id=team.id,
            params=_classification_params(output_property_name="my_prediction"),
        )

    assert "output_property_unprefixed" in _codes(report.findings)
    warn_finding = next(f for f in report.findings if f.code == "output_property_unprefixed")
    assert warn_finding.severity is contracts.ValidationSeverity.WARN


@pytest.mark.django_db
def test_hogql_count_failure_degrades_to_info(team):
    """A failed count query produces an info finding rather than raising.

    Mock side-effect order matches the call order in run_validation:
    1. training-population count -> raises
    2. inference-population count -> succeeds
    3. classification positives count -> succeeds
    """
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[RuntimeError("clickhouse blew up"), _stub_hogql_results([10_000]), _stub_hogql_results([300])],
    ):
        report = logic.run_validation(team_id=team.id, params=_classification_params())

    # No exception escaped; we got a structured report. Failed-count fingerprint present.
    assert "training_population_count_failed" in _codes(report.findings)
    assert report.summary.estimated_training_rows is None
    # Inference count still landed because the two paths are independent.
    assert report.summary.estimated_inference_rows == 10_000


@pytest.mark.django_db
def test_regression_emits_label_volume_caveat(team):
    """Regression validation explicitly notes label volume isn't yet checked."""
    params = contracts.CreatePipelineInput(
        name="reg_test",
        task_type=TaskType.REGRESSION,
        config={"target_expression": "toFloat(properties.value)", "horizon_days": 30},
        training_population={"kind": "hogql", "query": "SELECT person_id FROM events"},
        inference_population={"kind": "hogql", "query": "SELECT person_id FROM events"},
    )
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([20_000]), _stub_hogql_results([10_000])],
    ):
        report = logic.run_validation(team_id=team.id, params=params)

    assert "regression_label_volume_unchecked" in _codes(report.findings)
    # Population was sized correctly.
    assert report.summary.estimated_training_rows == 20_000


@pytest.mark.django_db
def test_forecasting_grain_invalid_blocks(team):
    """An out-of-set grain blocks before any data-touching check runs."""
    params = contracts.CreatePipelineInput(
        name="fcst_test",
        task_type=TaskType.FORECASTING,
        config={
            "series_expression": "count()",
            "grain": "fortnight",  # not in the allowed set
            "horizon_steps": 14,
        },
        training_population={"kind": "hogql", "query": "SELECT 1"},
        inference_population={"kind": "hogql", "query": "SELECT 1"},
    )
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([5_000])],
    ):
        report = logic.run_validation(team_id=team.id, params=params)

    assert report.ok is False
    assert "grain_invalid" in _codes(report.findings)


@pytest.mark.django_db
def test_forecasting_series_count_lands_on_summary(team):
    """When series_key is set + safe, the validator runs an extra count and lands the number in the summary."""
    params = contracts.CreatePipelineInput(
        name="fcst_series",
        task_type=TaskType.FORECASTING,
        config={
            "series_expression": "count()",
            "grain": "day",
            "horizon_steps": 7,
            "series_key": "team_id",
        },
        training_population={"kind": "hogql", "query": "SELECT 1"},
        inference_population={"kind": "hogql", "query": "SELECT team_id FROM events"},
    )
    # Four counts fire: training, inference, then series count when series_key is set.
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[
            _stub_hogql_results([10_000]),  # training pop
            _stub_hogql_results([5_000]),  # inference pop
            _stub_hogql_results([42]),  # distinct series
        ],
    ):
        report = logic.run_validation(team_id=team.id, params=params)

    assert report.summary.estimated_series_count == 42


@pytest.mark.django_db
def test_clustering_cluster_count_warning(team):
    """Requesting too many clusters relative to training size produces a warn finding."""
    params = contracts.CreatePipelineInput(
        name="clust_test",
        task_type=TaskType.CLUSTERING,
        config={"cluster_count": 500},
        training_population={"kind": "hogql", "query": "SELECT person_id FROM events"},
        inference_population={"kind": "hogql", "query": "SELECT person_id FROM events"},
    )
    # 10k training rows / 500 clusters = 20 per cluster -> below the 50 floor.
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([1_000])],
    ):
        report = logic.run_validation(team_id=team.id, params=params)

    assert "cluster_count_too_high_for_volume" in _codes(report.findings)
    assert report.summary.estimated_rows_per_cluster == pytest.approx(20.0)


@pytest.mark.django_db
def test_clustering_distance_metric_invalid_blocks(team):
    """An unrecognised distance metric blocks creation."""
    params = contracts.CreatePipelineInput(
        name="clust_metric",
        task_type=TaskType.CLUSTERING,
        config={"distance_metric": "chebyshev"},
        training_population={"kind": "hogql", "query": "SELECT 1"},
        inference_population={"kind": "hogql", "query": "SELECT 1"},
    )
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([1_000])],
    ):
        report = logic.run_validation(team_id=team.id, params=params)

    assert report.ok is False
    assert "distance_metric_invalid" in _codes(report.findings)


@pytest.mark.django_db
def test_population_kind_not_counted(team):
    """Cohort-id populations are accepted but skipped by the population-sizing checks.

    Classification's positives-count query still runs (it queries ``events`` directly
    for the target_event, independent of population kind), so we expect exactly one
    HogQL call on this path — the positives count.
    """
    params = _classification_params(
        training_population={"kind": "cohort_id", "id": 42},
        inference_population={"kind": "cohort_id", "id": 99},
    )
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([300])],
    ) as mock_exec:
        report = logic.run_validation(team_id=team.id, params=params)

    # One call — the classification positives count. Population sizing was skipped.
    assert mock_exec.call_count == 1
    assert "training_population_kind_not_counted" in _codes(report.findings)
    assert "inference_population_kind_not_counted" in _codes(report.findings)
    assert report.summary.estimated_training_rows is None
    assert report.summary.estimated_inference_rows is None
    # Positives still landed.
    assert report.summary.estimated_positive_count == 300


@pytest.mark.django_db
def test_team_not_found_blocks(team):
    """A nonexistent team blocks before any data check runs.

    Requires the ``team`` fixture so conftest's autouse team-scope fixture
    has something to set scope against; the validation call itself uses a
    different team_id to exercise the not-found path.
    """
    _ = team
    report = logic.run_validation(team_id=999_999_999, params=_classification_params())
    assert report.ok is False
    assert "team_not_found" in _codes(report.findings)


@pytest.mark.django_db
def test_adoption_framing_emits_reminder(team):
    """Adoption framing always emits the exclusion-reminder info finding."""
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([20_000]), _stub_hogql_results([5_000]), _stub_hogql_results([800])],
    ):
        report = logic.run_validation(team_id=team.id, params=_classification_params())

    info_codes = {f.code for f in report.findings if f.severity is contracts.ValidationSeverity.INFO}
    assert "adoption_framing_requires_exclusion" in info_codes
    assert "censoring_reminder" in info_codes


@pytest.mark.django_db
def test_retraining_more_frequent_than_inference_is_info(team):
    """Faster retraining than inference is allowed but flagged as info."""
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([10_000]), _stub_hogql_results([1_000]), _stub_hogql_results([300])],
    ):
        report = logic.run_validation(
            team_id=team.id,
            params=_classification_params(
                inference_cadence=Cadence.WEEKLY,
                retraining_cadence=Cadence.DAILY,
            ),
        )

    info_codes = {f.code for f in report.findings if f.severity is contracts.ValidationSeverity.INFO}
    assert "retraining_more_frequent_than_inference" in info_codes
