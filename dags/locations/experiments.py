"""
EXPERIMENTS LOCATION FILE

This module organizes experiment assets into a complete Dagster location.
It takes the individual assets defined in experiments.py and bundles them
with shared resources to create a complete Dagster definitions object.

Structure:
- experiments.py: Creates individual assets and jobs
- locations/experiments.py: Bundles everything with resources
- Dagster: Imports this location and integrates with other locations

Key concepts:
- Assets: Individual data products (experiment-metric analyses)
- Jobs: Collections of assets that run together
- Schedules: Automatic triggers for jobs
- Resources: Shared infrastructure (databases, storage, etc.)
- Definitions: Complete package that Dagster can load
"""

import dagster

# Import shared resources used across all locations
from . import resources

# Import all experiment-related definitions
from dags import experiments


def _create_definitions():
    """
    Bundle all experiment components into a complete Dagster definitions object.
    
    This function creates the final Dagster definitions that will be loaded
    by the Dagster instance. It handles both cases: when experiments exist
    and when no experiments are found.
    
    Returns:
        Dagster Definitions object containing assets, jobs, schedules, and resources
    """
    
    # Always include the computation job (placeholder or real)
    jobs = [experiments.experiment_computation_job]
    
    # Only include schedule if experiments were found
    schedules = []
    if experiments.daily_experiment_computation_schedule is not None:
        schedules.append(experiments.daily_experiment_computation_schedule)
        print("📅 Added daily computation schedule to definitions")
    else:
        print("⚠️  No schedule added (no experiments found)")
    
    # Create the complete Dagster definitions
    definitions = dagster.Definitions(
        # All experiment assets (may be empty list)
        assets=experiments.experiment_assets,
        
        # Jobs to run assets together
        jobs=jobs,
        
        # Automatic scheduling
        schedules=schedules,
        
        # Shared infrastructure: database connections, S3 storage, etc.
        resources=resources,
    )
    
    # Log summary for debugging
    asset_count = len(experiments.experiment_assets)
    job_count = len(jobs)
    schedule_count = len(schedules)
    
    print(f"📦 Created Dagster definitions with:")
    print(f"   • {asset_count} assets (individual experiment-metric analyses)")
    print(f"   • {job_count} jobs (ways to run multiple assets together)")  
    print(f"   • {schedule_count} schedules (automatic triggers)")
    print(f"   • Shared resources (database connections, etc.)")
    
    return definitions


# =============================================================================
# Module initialization
# =============================================================================

# Create the definitions object when this module is imported
print("🏗️  Building experiment location definitions...")
defs = _create_definitions()
print("✅ Experiment location ready for Dagster!")

# =============================================================================
# Integration notes
# =============================================================================
#
# This location integrates with the broader Dagster system as follows:
#
# 1. Dagster discovers this file through workspace.yaml configuration
# 2. Dagster imports the 'defs' variable from this module
# 3. Dagster combines definitions from all locations into one unified system
# 4. Users interact with assets through the Dagster UI or API
#
# Data flow:
# Database → experiments.py → locations/experiments.py → Dagster UI 