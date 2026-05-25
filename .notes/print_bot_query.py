import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.database.database import Database  # noqa: E402
from posthog.hogql.parser import parse_select  # noqa: E402
from posthog.hogql.printer import print_ast  # noqa: E402
from posthog.hogql.context import HogQLContext  # noqa: E402
from posthog.models import Team  # noqa: E402

team = Team.objects.first()
db = Database.create_for(team=team)
ctx = HogQLContext(database=db, team_id=team.id, enable_select_queries=True)

q = parse_select(
    """
    SELECT service_name, $virt_is_bot, $virt_bot_name
    FROM logs
    WHERE service_name = 'test-cdn-bot-analytics'
    LIMIT 1
    """
)
ch_sql = print_ast(q, ctx, "clickhouse")
print("--- HogQL → ClickHouse ---")
print(ch_sql)
