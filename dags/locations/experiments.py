"""
This module organizes experiment assets into a complete Dagster location.
It takes the individual assets defined in experiment_regular_metrics_timeseries.py and experiment_saved_metrics_timeseries.py and bundles them
with shared resources to create a complete Dagster definitions object.
"""

import dagster

from dags import experiment_regular_metrics_timeseries, experiment_saved_metrics_timeseries

from . import resources


def _create_definitions():
    """
    Bundle all experiment components into a complete Dagster definitions object.
    """

    jobs = [
        experiment_regular_metrics_timeseries.experiment_regular_metrics_timeseries_job,
        experiment_saved_metrics_timeseries.experiment_saved_metrics_timeseries_job,
    ]
    sensors = [
        experiment_regular_metrics_timeseries.experiment_regular_metrics_timeseries_discovery_sensor,
        experiment_saved_metrics_timeseries.experiment_saved_metrics_timeseries_discovery_sensor,
    ]
    schedules = [
        experiment_regular_metrics_timeseries.experiment_regular_metrics_timeseries_refresh_schedule,
        experiment_saved_metrics_timeseries.experiment_saved_metrics_timeseries_refresh_schedule,
    ]

    definitions = dagster.Definitions(
        assets=[
            experiment_regular_metrics_timeseries.experiment_regular_metrics_timeseries,
            experiment_saved_metrics_timeseries.experiment_saved_metrics_timeseries,
        ],
        jobs=jobs,
        sensors=sensors,
        schedules=schedules,
        resources=resources,
    )

    return definitions


defs = _create_definitions()
