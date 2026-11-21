from django.apps import AppConfig

from posthog.notebook_warehouse_tables import NotebookTableLineageSync, register_notebook_table_lineage_sync


def _load_notebook_table_lineage_sync() -> NotebookTableLineageSync:
    from products.data_modeling.backend.logic.notebook_table_dag_sync import sync_notebook_table_to_dag  # noqa: PLC0415

    return sync_notebook_table_to_dag


class DataModelingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.data_modeling.backend"
    label = "data_modeling"

    def ready(self):
        from . import signals  # noqa: F401

        register_notebook_table_lineage_sync(_load_notebook_table_lineage_sync)
