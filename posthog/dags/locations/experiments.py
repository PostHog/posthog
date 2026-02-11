"""
This module organizes experiment assets into a complete Dagster location.
It takes the individual assets defined in products.experiments.dags and bundles them
with shared resources to create a complete Dagster definitions object.
"""

import dagster

from products.experiments.dags import experiment_timeseries_recalculation

from . import resources


def _create_definitions():
    """
    Bundle all experiment components into a complete Dagster definitions object.
    """

    jobs = [
        experiment_timeseries_recalculation.experiment_timeseries_recalculation_job,
    ]
    sensors = [
        experiment_timeseries_recalculation.experiment_timeseries_recalculation_sensor,
    ]

    definitions = dagster.Definitions(
        assets=[
            experiment_timeseries_recalculation.experiment_timeseries_recalculation,
        ],
        jobs=jobs,
        sensors=sensors,
        resources=resources,
    )

    return definitions


defs = _create_definitions()
