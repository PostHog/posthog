import dagster

from products.signals.dags.inbox_ranking.common import is_inbox_ranking_registered
from products.signals.dags.inbox_ranking.dataset import dag as inbox_ranking_dataset
from products.signals.dags.inbox_ranking.training import dag as inbox_ranking_training

from . import loggers, resources

# The inbox-ranking dataset reads US Postgres/ClickHouse plus the US dogfood project's label
# events; EU has neither, so the definitions register on US (and non-cloud) only.
if is_inbox_ranking_registered():
    defs = dagster.Definitions(
        assets=[
            inbox_ranking_dataset.inbox_report_state,
            inbox_ranking_dataset.inbox_report_embeddings,
            inbox_ranking_dataset.inbox_signal_embeddings,
            inbox_ranking_dataset.inbox_report_labels,
            inbox_ranking_dataset.inbox_report_model_data,
            inbox_ranking_training.inbox_ranking_training_examples,
            inbox_ranking_training.inbox_ranking_model_candidate,
            inbox_ranking_training.inbox_ranking_model_champion,
        ],
        jobs=[inbox_ranking_dataset.inbox_ranking_dataset_job, inbox_ranking_training.inbox_ranking_training_job],
        schedules=[
            inbox_ranking_dataset.inbox_ranking_dataset_schedule,
            inbox_ranking_training.inbox_ranking_training_schedule,
        ],
        loggers=loggers,
        resources=resources,
    )
else:
    defs = dagster.Definitions(loggers=loggers, resources=resources)
