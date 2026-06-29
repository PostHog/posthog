"""
Model-class wiring for data_warehouse.

Light re-export of the data_warehouse model class(es) consumed cross-product.
"""

from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.models.team_data_warehouse_config import TeamDataWarehouseConfig

__all__ = ["ExternalDataSourceRevenueAnalyticsConfig", "TeamDataWarehouseConfig"]
