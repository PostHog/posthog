#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models.team import Team
from products.data_warehouse.backend.models import DataWarehouseSavedQuery

team = Team.objects.get(id=1)

# List all views for this team
print("=== All saved queries/views for team 1 ===")
views = DataWarehouseSavedQuery.objects.filter(team_id=1)
for v in views:
    print(f"  {v.name}")

# Check if revenue_analytics_customer is one of them
print()
print("=== Checking for revenue_analytics combined views ===")
for view in views:
    if 'revenue_analytics' in view.name and not '.' in view.name:
        print(f"  Found: {view.name}")
        print(f"    Query: {view.query[:200]}...")
