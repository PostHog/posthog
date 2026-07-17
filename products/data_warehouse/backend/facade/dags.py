"""
Dagster-assets wiring for data_warehouse.

Re-exports the Dagster asset module(s) that core's Dagster code location loads. These
live at the product root (``products/data_warehouse/dags``), outside ``backend.*``, so
they cross the boundary as objects via the facade rather than being imported directly.
"""

from products.data_warehouse.dags import managed_viewset_sync

__all__ = ["managed_viewset_sync"]
