import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Extra
from pydantic import Field as PydanticField

from posthog.hogql.database import (
    DatabaseField,
    FieldTraverser,
    LazyTable,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)

# NOTE: when you add new AST fields or nodes, add them to the Visitor classes in visitor.py as well!

camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class AST(BaseModel):
    class Config:
        extra = Extra.forbid

    def accept(self, visitor):
        camel_case_name = camel_case_pattern.sub("_", self.__class__.__name__).lower()
        method_name = f"visit_{camel_case_name}"
        if hasattr(visitor, method_name):
            visit = getattr(visitor, method_name)
            return visit(self)
        if hasattr(visitor, "visit_unknown"):
            return visitor.visit_unknown(self)
        raise ValueError(f"Visitor has no method {method_name}")


class Ref(AST):
    def get_child(self, name: str) -> "Ref":
        raise NotImplementedError("Ref.get_child not overridden")

    def has_child(self, name: str) -> bool:
        return self.get_child(name) is not None


class Expr(AST):
    ref: Optional[Ref]


class Macro(Expr):
    name: str
    expr: Expr
    # Whether the macro is an inlined column "SELECT 1 AS a" or a subquery "SELECT a AS (SELECT 1)"
    type: Literal["column", "subquery"]


class FieldAliasRef(Ref):
    name: str
    ref: Ref

    def get_child(self, name: str) -> Ref:
        return self.ref.get_child(name)

    def has_child(self, name: str) -> bool:
        return self.ref.has_child(name)


class BaseTableRef(Ref):
    def resolve_database_table(self) -> Table:
        raise NotImplementedError("BaseTableRef.resolve_database_table not overridden")

    def has_child(self, name: str) -> bool:
        return self.resolve_database_table().has_field(name)

    def get_child(self, name: str) -> Ref:
        if name == "*":
            return AsteriskRef(table=self)
        if self.has_child(name):
            field = self.resolve_database_table().get_field(name)
            if isinstance(field, LazyTable):
                return LazyTableRef(table=self, field=name, lazy_table=field)
            if isinstance(field, FieldTraverser):
                return FieldTraverserRef(table=self, chain=field.chain)
            if isinstance(field, VirtualTable):
                return VirtualTableRef(table=self, field=name, virtual_table=field)
            return FieldRef(name=name, table=self)
        raise ValueError(f"Field not found: {name}")


class TableRef(BaseTableRef):
    table: Table

    def resolve_database_table(self) -> Table:
        return self.table


class TableAliasRef(BaseTableRef):
    name: str
    table_ref: TableRef

    def resolve_database_table(self) -> Table:
        return self.table_ref.table


class LazyTableRef(BaseTableRef):
    table: BaseTableRef
    field: str
    lazy_table: LazyTable

    def resolve_database_table(self) -> Table:
        return self.lazy_table.table


class VirtualTableRef(BaseTableRef):
    table: BaseTableRef
    field: str
    virtual_table: VirtualTable

    def resolve_database_table(self) -> Table:
        return self.virtual_table

    def has_child(self, name: str) -> bool:
        return self.virtual_table.has_field(name)


class SelectQueryRef(Ref):
    # all aliases a select query has access to in its scope
    aliases: Dict[str, FieldAliasRef] = PydanticField(default_factory=dict)
    # all refs a select query exports
    columns: Dict[str, Ref] = PydanticField(default_factory=dict)
    # all from and join, tables and subqueries with aliases
    tables: Dict[
        str, Union[BaseTableRef, "SelectUnionQueryRef", "SelectQueryRef", "SelectQueryAliasRef"]
    ] = PydanticField(default_factory=dict)
    macros: Dict[str, Macro] = PydanticField(default_factory=dict)
    # all from and join subqueries without aliases
    anonymous_tables: List[Union["SelectQueryRef", "SelectUnionQueryRef"]] = PydanticField(default_factory=list)

    def get_alias_for_table_ref(
        self,
        table_ref: Union[BaseTableRef, "SelectUnionQueryRef", "SelectQueryRef", "SelectQueryAliasRef"],
    ) -> Optional[str]:
        for key, value in self.tables.items():
            if value == table_ref:
                return key
        return None

    def get_child(self, name: str) -> Ref:
        if name == "*":
            return AsteriskRef(table=self)
        if name in self.columns:
            return FieldRef(name=name, table=self)
        raise ValueError(f"Column not found: {name}")

    def has_child(self, name: str) -> bool:
        return name in self.columns


class SelectUnionQueryRef(Ref):
    refs: List[SelectQueryRef]

    def get_alias_for_table_ref(
        self,
        table_ref: Union[BaseTableRef, SelectQueryRef, "SelectQueryAliasRef"],
    ) -> Optional[str]:
        return self.refs[0].get_alias_for_table_ref(table_ref)

    def get_child(self, name: str) -> Ref:
        return self.refs[0].get_child(name)

    def has_child(self, name: str) -> bool:
        return self.refs[0].has_child(name)


class SelectQueryAliasRef(Ref):
    name: str
    ref: SelectQueryRef | SelectUnionQueryRef

    def get_child(self, name: str) -> Ref:
        if name == "*":
            return AsteriskRef(table=self)
        if self.ref.has_child(name):
            return FieldRef(name=name, table=self)
        raise ValueError(f"Field {name} not found on query with alias {self.name}")

    def has_child(self, name: str) -> bool:
        return self.ref.has_child(name)


SelectQueryRef.update_forward_refs(SelectQueryAliasRef=SelectQueryAliasRef)


class CallRef(Ref):
    name: str
    args: List[Ref]


class ConstantRef(Ref):
    value: Any


class AsteriskRef(Ref):
    table: BaseTableRef | SelectQueryRef | SelectQueryAliasRef | SelectUnionQueryRef


class FieldTraverserRef(Ref):
    chain: List[str]
    table: BaseTableRef | SelectQueryRef | SelectQueryAliasRef | SelectUnionQueryRef


class FieldRef(Ref):
    name: str
    table: BaseTableRef | SelectQueryRef | SelectQueryAliasRef | SelectUnionQueryRef

    def resolve_database_field(self) -> Optional[DatabaseField]:
        if isinstance(self.table, BaseTableRef):
            table = self.table.resolve_database_table()
            if table is not None:
                return table.get_field(self.name)
        return None

    def get_child(self, name: str) -> Ref:
        database_field = self.resolve_database_field()
        if database_field is None:
            raise ValueError(f'Can not access property "{name}" on field "{self.name}".')
        if isinstance(database_field, StringJSONDatabaseField):
            return PropertyRef(name=name, parent=self)
        raise ValueError(
            f'Can not access property "{name}" on field "{self.name}" of type: {type(database_field).__name__}'
        )


class PropertyRef(Ref):
    name: str
    parent: FieldRef

    # The property has been moved into a field we query from a joined subquery
    joined_subquery: Optional[SelectQueryAliasRef]
    joined_subquery_field_name: Optional[str]

    def get_child(self, name: str) -> "Ref":
        raise NotImplementedError("JSON property traversal is not yet supported")

    def has_child(self, name: str) -> bool:
        return False


class Alias(Expr):
    alias: str
    expr: Expr


class BinaryOperationType(str, Enum):
    Add = "+"
    Sub = "-"
    Mult = "*"
    Div = "/"
    Mod = "%"


class BinaryOperation(Expr):
    left: Expr
    right: Expr
    op: BinaryOperationType


class And(Expr):
    class Config:
        extra = Extra.forbid

    exprs: List[Expr]


class Or(Expr):
    class Config:
        extra = Extra.forbid

    exprs: List[Expr]


class CompareOperationType(str, Enum):
    Eq = "=="
    NotEq = "!="
    Gt = ">"
    GtE = ">="
    Lt = "<"
    LtE = "<="
    Like = "like"
    ILike = "ilike"
    NotLike = "not like"
    NotILike = "not ilike"
    In = "in"
    NotIn = "not in"
    Regex = "=~"
    NotRegex = "!~"


class CompareOperation(Expr):
    left: Expr
    right: Expr
    op: CompareOperationType


class Not(Expr):
    expr: Expr


class OrderExpr(Expr):
    expr: Expr
    order: Literal["ASC", "DESC"] = "ASC"


class Constant(Expr):
    value: Any


class Field(Expr):
    chain: List[str]


class Placeholder(Expr):
    field: str


class Call(Expr):
    name: str
    args: List[Expr]
    distinct: Optional[bool] = None


class JoinExpr(Expr):
    join_type: Optional[str] = None
    table: Optional[Union["SelectQuery", "SelectUnionQuery", Field]] = None
    alias: Optional[str] = None
    table_final: Optional[bool] = None
    constraint: Optional[Expr] = None
    next_join: Optional["JoinExpr"] = None
    sample: Optional["SampleExpr"] = None


class SelectQuery(Expr):
    ref: Optional[SelectQueryRef] = None
    macros: Optional[Dict[str, Macro]] = None
    select: List[Expr]
    distinct: Optional[bool] = None
    select_from: Optional[JoinExpr] = None
    where: Optional[Expr] = None
    prewhere: Optional[Expr] = None
    having: Optional[Expr] = None
    group_by: Optional[List[Expr]] = None
    order_by: Optional[List[OrderExpr]] = None
    limit: Optional[Expr] = None
    limit_by: Optional[List[Expr]] = None
    limit_with_ties: Optional[bool] = None
    offset: Optional[Expr] = None


class SelectUnionQuery(Expr):
    ref: Optional[SelectUnionQueryRef] = None
    select_queries: List[SelectQuery]


class RatioExpr(Expr):
    left: Constant
    right: Optional[Constant] = None


class SampleExpr(Expr):
    # k or n
    sample_value: RatioExpr
    offset_value: Optional[RatioExpr]


JoinExpr.update_forward_refs(SampleExpr=SampleExpr)
JoinExpr.update_forward_refs(SelectUnionQuery=SelectUnionQuery)
JoinExpr.update_forward_refs(SelectQuery=SelectQuery)
