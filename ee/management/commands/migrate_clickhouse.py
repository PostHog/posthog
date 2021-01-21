from django.core.management.base import BaseCommand
from infi.clickhouse_orm import Database  # type: ignore

from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HTTP_URL, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def handle(self, *args, **options):
        try:
            Database(
                CLICKHOUSE_DATABASE,
                db_url=CLICKHOUSE_HTTP_URL,
                username=CLICKHOUSE_USER,
                password=CLICKHOUSE_PASSWORD,
                verify_ssl_cert=False,
            ).migrate("ee.clickhouse.migrations")
            print("migration successful")
        except Exception as e:
            print(e)
