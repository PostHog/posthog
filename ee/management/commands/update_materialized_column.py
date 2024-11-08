from argparse import BooleanOptionalAction
from django.core.management.base import BaseCommand, CommandParser

from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns
from ee.clickhouse.materialized_columns.columns import update_column_is_disabled


class Command(BaseCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("table")
        parser.add_argument("column_name")
        parser.add_argument("--enable", action=BooleanOptionalAction, required=True)

    def handle(self, table: TablesWithMaterializedColumns, column_name: ColumnName, enable: bool, **options):
        update_column_is_disabled(table, column_name, is_disabled=not enable)
