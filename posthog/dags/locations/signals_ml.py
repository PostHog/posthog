import dagster

from products.signals.dags.inbox_ranking.common import is_inbox_ranking_registered
from products.signals.dags.inbox_ranking.nn import (
    dag as inbox_ranking_nn,
    experiments as inbox_ranking_nn_experiments,
    pairs as inbox_ranking_nn_pairs,
)

from . import loggers, resources

# Runs on an image with the `inbox-ranking` dependency group. torch is imported only inside the
# candidate asset's body, so this module imports on the main image too. Registered on US (and
# non-cloud) only, behind the same gate as `signals.py`.
if is_inbox_ranking_registered():
    defs = dagster.Definitions(
        assets=[
            inbox_ranking_nn.inbox_ranking_nn_examples,
            inbox_ranking_nn.inbox_ranking_nn_model_candidate,
            inbox_ranking_nn.inbox_ranking_nn_model_champion,
            inbox_ranking_nn.inbox_ranking_nn_with_prio_model_candidate,
            inbox_ranking_nn.inbox_ranking_nn_with_prio_model_champion,
            inbox_ranking_nn_experiments.inbox_ranking_nn_experiment_candidates,
            inbox_ranking_nn_experiments.inbox_ranking_nn_pair_experiment_candidates,
            inbox_ranking_nn_pairs.inbox_ranking_nn_pair_examples,
        ],
        jobs=[
            inbox_ranking_nn.inbox_ranking_nn_training_job,
            inbox_ranking_nn_experiments.inbox_ranking_nn_experiments_job,
            inbox_ranking_nn_pairs.inbox_ranking_nn_pair_examples_job,
        ],
        schedules=[
            inbox_ranking_nn.inbox_ranking_nn_training_schedule,
            inbox_ranking_nn_experiments.inbox_ranking_nn_experiments_schedule,
        ],
        loggers=loggers,
        resources=resources,
    )
else:
    defs = dagster.Definitions(loggers=loggers, resources=resources)
