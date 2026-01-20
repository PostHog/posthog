from dataclasses import dataclass

from posthog.hogql import ast


@dataclass
class JoinExprResponse:
    printed_sql: str
    where: ast.Expr | None = None


@dataclass
class PrintableMaterializedColumn:
    table: str | None
    column: str
    is_nullable: bool

    def __str__(self) -> str:
        if self.table is None:
            # XXX: For legacy person properties handling (see comment at instantiation site.)
            return self.column
        else:
            return f"{self.table}.{self.column}"


@dataclass
class PrintableMaterializedPropertyGroupItem:
    table: str
    column: str
    property_name: str

    def __str__(self) -> str:
        # If the key we're looking for doesn't exist in the map for this property group, an empty string (the default
        # value for the `String` type) is returned. Since that is a valid property value, we need to check it here.
        return f"{self.has_expr} ? {self.value_expr} : null"

    @property
    def __qualified_column(self) -> str:
        return f"{self.table}.{self.column}"

    @property
    def has_expr(self) -> str:
        return f"has({self.__qualified_column}, {self.property_name})"

    @property
    def value_expr(self) -> str:
        return f"{self.__qualified_column}[{self.property_name}]"
