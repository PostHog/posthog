"""Shapes passed between the subject resolver, the check registry, and the compiler."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ..facade.enums import SubjectType

if TYPE_CHECKING:
    from posthog.hogql import ast


class Evaluation(StrEnum):
    """How the runner turns a compiled query's result row into a status."""

    ZERO_ROWS_PASS = "zero_rows_pass"
    BOUNDS = "bounds"


@dataclass(frozen=True)
class SubjectRef:
    """A resolved check subject.

    ``queryable_name`` is what the compiler puts in the FROM clause; it can differ from the stored
    ``subject_name`` after a rename, which is why the runner writes it back to the check row.
    """

    subject_type: SubjectType
    subject_uuid: str
    name: str
    queryable_name: str
    exists: bool


@dataclass(frozen=True)
class CheckPlan:
    """What a check type contributes to the compiled query.

    ``failing_rows`` selects the rows that violate the assertion; the compiler aggregates over it so
    nothing but counts ever leaves ClickHouse. A type whose headline number is not a row count
    (freshness) overrides ``failed_count_expr`` and ``observed_value_expr``.

    ``diagnostic_rows`` is the form a human re-runs. It exists because the two jobs pull apart:
    counting is cheapest over a constant projection, while investigating needs the offending values.
    A type whose failing rows already show something useful leaves it unset.
    """

    failing_rows: "ast.SelectQuery | ast.SelectSetQuery"
    diagnostic_rows: "ast.SelectQuery | ast.SelectSetQuery | None" = None
    failed_count_expr: "ast.Expr | None" = None
    observed_value_expr: "ast.Expr | None" = None
    evaluation: Evaluation = Evaluation.ZERO_ROWS_PASS


@dataclass(frozen=True)
class CompiledCheck:
    """A check ready to execute.

    Two printed forms, because they answer different questions. ``printed_query`` is the aggregate
    that actually runs. ``printed_failing_rows_query`` is the inner query on its own, which is what
    someone investigating a failure needs: since failing rows are never stored, re-running this is
    the only way to see them.
    """

    query: "ast.SelectQuery"
    printed_query: str
    printed_failing_rows_query: str
    evaluation: Evaluation
