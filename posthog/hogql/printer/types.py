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
    has_minmax_index: bool
    has_bloom_filter_index: bool
    has_ngram_lower_index: bool

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


@dataclass
class PrintableJSONSubcolumn:
    table: str | None
    column: str
    chain: list[str]
    raw_path_args: list[str]
    tuple_element_chain: list[str] | None = None
    typed_path_type: str | None = None
    cast_value_to_string: bool = False
    null_if_missing_or_null: bool = True

    def source_field(self) -> str:
        return self.column if self.table is None else f"{self.table}.{self.column}"

    def value_expression(self) -> str:
        source_field = self.source_field()
        field = self.column if self.table is None else f"({source_field})"
        if self.tuple_element_chain is not None:
            expression = field
            for chain_part in self.tuple_element_chain:
                expression = f"tupleElement({expression}, {chain_part})"
        else:
            expression = ".".join([field, *self.chain])
        if self.cast_value_to_string:
            expression = f"toString({expression})"
        return expression

    def raw_value_expression(self) -> str:
        path_args = ", ".join(self.raw_path_args)
        return f"JSONExtractRaw({self.source_field()}, {path_args})"

    def __str__(self) -> str:
        expression = self.value_expression()
        if self.null_if_missing_or_null:
            if self.typed_path_type == "String":
                return f"nullIf({expression}, '')"
            return f"if(has(['', 'null'], {self.raw_value_expression()}), NULL, {expression})"
        return expression
