#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models.team import Team
from posthog.hogql.query import execute_hogql_query

team = Team.objects.get(id=1)

# Check self-serve customer IDs in stub data
print("Self-serve customers in stub data:")
query = '''
SELECT id, name, JSONExtractString(metadata, 'revenue_source') as revenue_source
FROM "stripe.stub.customer_revenue_view"
WHERE JSONExtractString(metadata, 'revenue_source') = 'self-serve'
'''
result = execute_hogql_query(query=query, team=team)
for row in result.results:
    print(f"  {row[0]}: {row[1]} ({row[2]})")

# Check revenue items for self-serve customers
print("\nRevenue items for self-serve customers (customer_id like 'cus_1' to 'cus_5'):")
query = '''
SELECT
    customer_id,
    count(*) as item_count,
    sum(amount) / 100 as total_revenue_dollars
FROM "stripe.stub.revenue_item_revenue_view"
WHERE customer_id IN ('cus_1', 'cus_2', 'cus_3', 'cus_4', 'cus_5')
GROUP BY customer_id
ORDER BY customer_id
'''
result = execute_hogql_query(query=query, team=team)
total = 0
for row in result.results:
    print(f"  {row[0]}: {row[1]} items, ${row[2]:.2f}")
    total += row[2]
print(f"\nTotal revenue for self-serve: ${total:.2f}")

# Check all stub revenue
print("\nTotal stub revenue:")
query = '''
SELECT
    count(*) as item_count,
    sum(amount) / 100 as total_revenue_dollars
FROM "stripe.stub.revenue_item_revenue_view"
'''
result = execute_hogql_query(query=query, team=team)
print(f"  {result.results[0][0]} items, ${result.results[0][1]:.2f}")
