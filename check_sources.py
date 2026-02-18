#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.models import DataWarehouseSavedQuery

# Check all data sources (regardless of type)
sources = ExternalDataSource.objects.filter(team_id=1)
print('All data sources for team 1:')
for s in sources:
    config = ExternalDataSourceRevenueAnalyticsConfig.objects.filter(external_data_source=s).first()
    enabled = config.enabled if config else False
    print(f'  - prefix={repr(s.prefix)} type={s.source_type} rev_enabled={enabled}')

# Check tables
tables = DataWarehouseTable.objects.filter(team_id=1)
print(f'\nTables for team 1: {tables.count()}')
for t in tables[:15]:
    print(f'  - {t.name}')

# Check saved queries (views)
views = DataWarehouseSavedQuery.objects.filter(team_id=1)
print(f'\nSaved queries for team 1: {views.count()}')
for v in views:
    print(f'  - {v.name}')
