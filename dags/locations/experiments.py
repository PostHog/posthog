"""
This module organizes experiment assets into a complete Dagster location.
It takes the individual assets defined in experiments.py and bundles them
with shared resources to create a complete Dagster definitions object.
"""

import dagster

from . import resources

from dags import experiments


def _create_definitions():
    """
    Bundle all experiment components into a complete Dagster definitions object.
    """
    
    jobs = [experiments.experiment_computation_job]
    sensors = [experiments.experiment_discovery_sensor]
    schedules = [experiments.daily_experiment_full_refresh_schedule]  # Optional full refresh
    
    definitions = dagster.Definitions(
        assets=[experiments.experiment_metrics],
        jobs=jobs,
        sensors=sensors,
        schedules=schedules,
        resources=resources,
    )
    
    return definitions



defs = _create_definitions()