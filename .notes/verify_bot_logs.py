import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.clickhouse.query_tagging import tags_context  # noqa: E402
from posthog.hogql.query import execute_hogql_query  # noqa: E402
from posthog.models import Team  # noqa: E402

team = Team.objects.first()
print("Team:", team.id if team else None)

with tags_context(product="logs", feature="query"):
    res = execute_hogql_query(
        """
        SELECT
            service_name,
            $virt_is_bot,
            $virt_bot_name,
            $virt_traffic_type,
            $virt_traffic_category,
            $virt_bot_operator
        FROM logs
        WHERE service_name = 'test-cdn-bot-analytics'
        LIMIT 1
        """,
        team=team,
    )
print("columns:", res.columns)
print("results:", res.results)
print("hogql:", res.hogql)
