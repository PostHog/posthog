"""Shared building blocks for check-type specs.

Every identifier reaching a query goes through a HogQL AST node, never string interpolation, so
the printer's backtick escaping is the only thing standing between a hostile column name and the
generated SQL.
"""

from posthog.hogql import ast

from ..contracts import SubjectRef


def subject_source(subject: SubjectRef) -> ast.JoinExpr:
    return ast.JoinExpr(table=ast.Field(chain=list(subject.queryable_name.split("."))))


def column(column_name: str) -> ast.Field:
    return ast.Field(chain=list(column_name.split(".")))


def one() -> ast.Constant:
    """Placeholder projection for subqueries whose rows matter but whose values do not."""
    return ast.Constant(value=1)


def star() -> ast.Field:
    """Projection for the diagnostic form, where the offending row is the whole point."""
    return ast.Field(chain=["*"])


def diagnostic_of(failing_rows: ast.SelectQuery) -> ast.SelectQuery:
    """The same rows the check counts, projected so a human can see what broke."""
    return ast.SelectQuery(select=[star()], select_from=failing_rows.select_from, where=failing_rows.where)
