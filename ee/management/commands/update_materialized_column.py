import logging

from typing import Any
from collections.abc import Callable
from django.core.management.base import BaseCommand, CommandParser

from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns
from ee.clickhouse.materialized_columns.columns import update_column_is_disabled, drop_column

logger = logging.getLogger(__name__)

COLUMN_OPERATIONS: dict[str, Callable[[TablesWithMaterializedColumns, ColumnName], Any]] = {
    "enable": lambda table, column_name: update_column_is_disabled(table, column_name, is_disabled=False),
    "disable": lambda table, column_name: update_column_is_disabled(table, column_name, is_disabled=True),
    "drop": drop_column,
}


class Command(BaseCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("operation", choices=COLUMN_OPERATIONS.keys())
        parser.add_argument("table")
        parser.add_argument("column_name")

    def handle(self, operation: str, table: TablesWithMaterializedColumns, column_name: ColumnName, **options):
        logger.info("Running %r for %r.%r...", operation, table, column_name)
        fn = COLUMN_OPERATIONS[operation]
        fn(table, column_name)
        logger.info("Success!")
