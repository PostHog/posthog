#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from products.data_warehouse.backend.models import DataWarehouseSavedQuery

# Delete event-based revenue views for team 1
views = DataWarehouseSavedQuery.objects.filter(
    team_id=1,
    name__startswith='revenue_analytics.events'
)
count = views.count()
print(f"Deleting {count} event-based revenue views...")
views.delete()
print("Done!")
