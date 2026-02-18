#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models.team import Team
from posthog.hogql.query import execute_hogql_query

team = Team.objects.get(id=1)

# Check what the revenue analytics actually queries
# The query runner uses revenue_analytics_customer as an alias
print("Testing the filter that Revenue Analytics uses...")

# First check total revenue from combined view
query = '''
SELECT
    count(*) as item_count,
    sum(amount) as total_amount
FROM revenue_analytics_revenue_item
'''
try:
    result = execute_hogql_query(query=query, team=team)
    print(f"Total from revenue_analytics_revenue_item: {result.results[0][0]} items, {result.results[0][1]} cents")
except Exception as e:
    print(f"revenue_analytics_revenue_item: ERROR - {e}")

# Check distinct customers
query = '''
SELECT count(distinct customer_id)
FROM revenue_analytics_revenue_item
'''
try:
    result = execute_hogql_query(query=query, team=team)
    print(f"Distinct customers: {result.results[0][0]}")
except Exception as e:
    print(f"Distinct customers: ERROR - {e}")

# Now try with the HogQL filter for self-serve
print("\nWith self-serve filter:")
query = '''
SELECT
    count(*) as item_count,
    sum(revenue_analytics_revenue_item.amount) as total_amount
FROM revenue_analytics_revenue_item
JOIN revenue_analytics_customer ON revenue_analytics_revenue_item.customer_id = revenue_analytics_customer.id
WHERE JSONExtractString(revenue_analytics_customer.metadata, 'revenue_source') = 'self-serve'
'''
try:
    result = execute_hogql_query(query=query, team=team)
    print(f"Filtered: {result.results[0][0]} items, {result.results[0][1]} cents")
except Exception as e:
    print(f"Filtered: ERROR - {e}")
