"""
Dagster wiring for data_modeling.

Re-exports the Dagster job module(s) that core's Dagster code location loads. They live at the
product root (``products/data_modeling/dags``), outside ``backend.*``, so they cross the boundary
as objects via the facade rather than being imported directly.
"""

from products.data_modeling.dags import saved_query_demand

__all__ = ["saved_query_demand"]
