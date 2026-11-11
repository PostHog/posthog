import dagster

from . import loggers, resources

# Dagster Cloud loads this module as the team-logs location. Delete it only together with that location.
defs = dagster.Definitions(
    loggers=loggers,
    resources=resources,
)
