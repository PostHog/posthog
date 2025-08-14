import dagster

from dags.max_ai.run_evaluation import run_evaluation

from . import resources

defs = dagster.Definitions(
    jobs=[run_evaluation],
    resources=resources,
)
