#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models.team import Team
from posthog.hogql.query import execute_hogql_query

team = Team.objects.get(id=1)

# Check the stub revenue_item view
print("Checking stub data views for team 1...")

queries = [
    ('stripe.stub.revenue_item_revenue_view', 'SELECT count(*) FROM "stripe.stub.revenue_item_revenue_view"'),
    ('stripe.stub.customer_revenue_view', 'SELECT count(*) FROM "stripe.stub.customer_revenue_view"'),
]

for name, query in queries:
    try:
        result = execute_hogql_query(query=query, team=team)
        count = result.results[0][0] if result.results else 0
        print(f"  {name}: {count} rows")
    except Exception as e:
        print(f"  {name}: ERROR - {e}")

# Check if customer metadata has revenue_source
print("\nChecking customer metadata...")
try:
    query = '''
    SELECT
        JSONExtractString(metadata, 'revenue_source') as revenue_source,
        count(*) as cnt
    FROM "stripe.stub.customer_revenue_view"
    GROUP BY revenue_source
    '''
    result = execute_hogql_query(query=query, team=team)
    for row in result.results:
        print(f"  revenue_source='{row[0]}': {row[1]} customers")
except Exception as e:
    print(f"  ERROR: {e}")
