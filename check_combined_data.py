#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models.team import Team
from posthog.hogql.query import execute_hogql_query

team = Team.objects.get(id=1)

# Check what is in the combined customer view
print("=== Combined customer view (revenue_analytics_customer) ===")
query = '''
SELECT id, name, metadata
FROM revenue_analytics_customer
LIMIT 10
'''
try:
    result = execute_hogql_query(query=query, team=team)
    for row in result.results:
        print(f"  {row[0]}: {row[1]} - metadata: {row[2]}")
except Exception as e:
    print(f"  ERROR: {e}")

# Check what is in combined revenue item view
print()
print("=== Combined revenue item view (revenue_analytics_revenue_item) ===")
query = '''
SELECT customer_id, count(*), sum(amount)
FROM revenue_analytics_revenue_item
GROUP BY customer_id
LIMIT 10
'''
try:
    result = execute_hogql_query(query=query, team=team)
    for row in result.results:
        print(f"  {row[0]}: {row[1]} items, {row[2]} cents")
except Exception as e:
    print(f"  ERROR: {e}")

# Check if stub customer data exists
print()
print("=== Stub customer data (stripe.stub.customer_revenue_view) ===")
query = '''
SELECT id, name, metadata
FROM "stripe.stub.customer_revenue_view"
LIMIT 5
'''
try:
    result = execute_hogql_query(query=query, team=team)
    for row in result.results:
        print(f"  {row[0]}: {row[1]} - metadata: {row[2]}")
except Exception as e:
    print(f"  ERROR: {e}")

# Check if event customer data exists
print()
print("=== Event customer data (revenue_analytics.events.paid_bill.customer_events_revenue_view) ===")
query = '''
SELECT id, name, metadata
FROM "revenue_analytics.events.paid_bill.customer_events_revenue_view"
LIMIT 5
'''
try:
    result = execute_hogql_query(query=query, team=team)
    for row in result.results:
        print(f"  {row[0]}: {row[1]} - metadata: {row[2]}")
except Exception as e:
    print(f"  ERROR: {e}")
