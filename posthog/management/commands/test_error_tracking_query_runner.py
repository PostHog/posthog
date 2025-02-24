from posthog.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
from posthog.models.team import Team
import json

team = Team.objects.all().first()

test_data = """
{"query":{"kind":"ErrorTrackingQuery","orderBy":"last_seen","status":"active","dateRange":{"date_from":"-7d","date_to":null},"assignee":null,"filterGroup":{"type":"AND","values":[{"type":"AND","values":[{"key":"$active_feature_flags","value":null,"operator":"icontains","type":"event"}]}]},"filterTestAccounts":false,"searchQuery":"","limit":50},"client_query_id":"98910556-5c1b-4da4-8ecc-011c3f1cfda0","refresh":"async"}
"""

# Json parse the above
query = json.loads(test_data)["query"]

runner = ErrorTrackingQueryRunner(team=team, query=query)

print(runner.to_query())
