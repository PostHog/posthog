from dataclasses import dataclass

from common.hogql import ast


@dataclass
class JoinExprResponse:
    printed_sql: str
    where: ast.Expr | None = None
