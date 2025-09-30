"""
This module organizes experiment assets into a complete Dagster location.
It takes the individual assets defined in experiments.py and bundles them
with shared resources to create a complete Dagster definitions object.
"""

import dagster

from dags import experiments

from . import resources


def _create_definitions():
    """
    Bundle all experiment components into a complete Dagster definitions object.
    """

    jobs = [
        experiments.experiment_regular_metrics_job,
        experiments.experiment_saved_metrics_job,
    ]
    sensors = [
        experiments.experiment_regular_metrics_discovery_sensor,
        experiments.experiment_saved_metrics_discovery_sensor,
    ]
    schedules = [
        experiments.daily_experiment_regular_metrics_refresh_schedule,
        experiments.daily_experiment_saved_metrics_refresh_schedule,
    ]

    definitions = dagster.Definitions(
        assets=[
            experiments.experiment_regular_metrics_timeseries,
            experiments.experiment_saved_metrics_timeseries,
        ],
        jobs=jobs,
        sensors=sensors,
        schedules=schedules,
        resources=resources,
    )

    return definitions


defs = _create_definitions()
