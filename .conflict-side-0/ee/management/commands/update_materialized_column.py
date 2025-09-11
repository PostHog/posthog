import logging
from collections.abc import Callable, Iterable
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns

from ee.clickhouse.materialized_columns.columns import drop_column, update_column_is_disabled

logger = logging.getLogger(__name__)

COLUMN_OPERATIONS: dict[str, Callable[[TablesWithMaterializedColumns, Iterable[ColumnName]], Any]] = {
    "enable": lambda table, column_names: update_column_is_disabled(table, column_names, is_disabled=False),
    "disable": lambda table, column_names: update_column_is_disabled(table, column_names, is_disabled=True),
    "drop": drop_column,
}


class Command(BaseCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("operation", choices=COLUMN_OPERATIONS.keys())
        parser.add_argument("table")
        parser.add_argument("column_names", nargs="+", metavar="column")

    def handle(
        self, operation: str, table: TablesWithMaterializedColumns, column_names: Iterable[ColumnName], **options
    ):
        logger.info("Running %r on %r for %r...", operation, table, column_names)
        fn = COLUMN_OPERATIONS[operation]
        fn(table, column_names)
        logger.info("Success!")
