from abc import ABC, abstractmethod
import dataclasses
from typing import Optional
from collections.abc import Iterator
import psycopg.rows
import pyarrow as pa
import psycopg

from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.warehouse.models import IncrementalFieldType

from dlt.common.normalizers.naming.snake_case import NamingConvention


@dataclasses.dataclass
class Column:
    name: str
    data_type: str
    nullable: bool | None = None
    numeric_scale: int | None = None
    numeric_precision: int | None = None


@dataclasses.dataclass
class Table:
    name: str
    columns: list[Column]


class Source(ABC):
    _inputs: dict[str, str]
    _logger: FilteringBoundLogger

    def __init__(self, inputs: dict[str, str], logger: FilteringBoundLogger) -> None:
        self._inputs = inputs
        self._logger = logger

    @property
    def name(self) -> str:
        raise NotImplementedError

    def log(self, msg: str) -> None:
        self._logger.debug(msg)

    @abstractmethod
    def get_rows(self) -> Iterator[list | dict | pa.Table]:
        raise NotImplementedError

    @abstractmethod
    def get_tables(self) -> list[Table]:
        raise NotImplementedError

    @abstractmethod
    def get_primary_keys(self) -> list[str] | None:
        raise NotImplementedError

    @abstractmethod
    def get_table_counts(self) -> list[tuple[str, int]]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def filter_incremental_fields(columns: list[Column]) -> list[tuple[Column, IncrementalFieldType]]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def validate_connection() -> bool:
        raise NotImplementedError


class PostgresSource(Source):
    _table_name: str

    def __init__(self, inputs: dict[str, str], logger: FilteringBoundLogger, table_name: str) -> None:
        super().__init__(inputs, logger)

        self._table_name = table_name

    def _get_connection(self, cursor: Optional[type[psycopg.Cursor]] = None):
        host = self._inputs.get("host")
        port = self._inputs.get("port")
        user = self._inputs.get("user")
        password = self._inputs.get("password")
        database = self._inputs.get("database")

        with psycopg.connect(
            f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=prefer", cursor_factory=cursor
        ) as connection:
            yield connection

    @property
    def name(self):
        return NamingConvention().normalize_identifier(self._table_name)

    def get_rows(self):
        pass

    def get_tables(self):
        pass

    def get_primary_keys(self):
        pass

    def get_row_counts(self):
        pass

    @staticmethod
    def filter_incremental_fields():
        pass

    @staticmethod
    def validate_connection():
        pass
