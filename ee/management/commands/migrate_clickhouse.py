from django.core.management.base import BaseCommand
from infi.clickhouse_orm import Database

from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USERNAME,
    CLICKHOUSE_VERIFY,
)


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def handle(self, *args, **options):
        Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USERNAME,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=False,
        ).migrate("ee.clickhouse.migrations")
