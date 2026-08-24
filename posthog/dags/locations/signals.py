import dagster

from products.signals.dags.inbox_ranking.common import is_inbox_ranking_registered
from products.signals.dags.inbox_ranking.dataset import dag as inbox_ranking_dataset

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
        ],
        jobs=[inbox_ranking_dataset.inbox_ranking_dataset_job],
        schedules=[inbox_ranking_dataset.inbox_ranking_dataset_schedule],
        loggers=loggers,
        resources=resources,
    )
else:
    defs = dagster.Definitions(loggers=loggers, resources=resources)
