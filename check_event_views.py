#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models.team import Team
from posthog.hogql.query import execute_hogql_query

team = Team.objects.get(id=1)

print("Checking event-based revenue views...")

# Check event-based revenue_item view
try:
    query = 'SELECT count(*) FROM "revenue_analytics.events.paid_bill.revenue_item_events_revenue_view"'
    result = execute_hogql_query(query=query, team=team)
    count = result.results[0][0] if result.results else 0
    print(f"  events.revenue_item: {count} rows")
except Exception as e:
    print(f"  events.revenue_item: ERROR - {e}")

# Check event-based customer view
try:
    query = 'SELECT count(*) FROM "revenue_analytics.events.paid_bill.customer_events_revenue_view"'
    result = execute_hogql_query(query=query, team=team)
    count = result.results[0][0] if result.results else 0
    print(f"  events.customer: {count} rows")
except Exception as e:
    print(f"  events.customer: ERROR - {e}")

print("\nChecking stub data views...")

# Check stub revenue_item view
try:
    query = 'SELECT count(*) FROM "stripe.stub.revenue_item_revenue_view"'
    result = execute_hogql_query(query=query, team=team)
    count = result.results[0][0] if result.results else 0
    print(f"  stripe.stub.revenue_item: {count} rows")
except Exception as e:
    print(f"  stripe.stub.revenue_item: ERROR - {e}")

# Check stub customer view
try:
    query = 'SELECT count(*) FROM "stripe.stub.customer_revenue_view"'
    result = execute_hogql_query(query=query, team=team)
    count = result.results[0][0] if result.results else 0
    print(f"  stripe.stub.customer: {count} rows")
except Exception as e:
    print(f"  stripe.stub.customer: ERROR - {e}")
