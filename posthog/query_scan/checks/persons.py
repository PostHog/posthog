"""Decide whether a query joins the persons table without pushing a filter into it.

``select_from_persons_table`` builds a subquery that deduplicates every person version for
the project. With no filter inside it, that subquery reads every person row on every run, so
a query over a few million events can be dominated by the join.

The subqueries come from ``HogQLContext.persons_selects``, which the schema records while it
builds them. Reading them back from the prepared tree would mean pattern-matching a shape
that changes with the argMax version and the pushdown modifier.

A read straight from the persons table builds the same subquery, and the advice here does not
fit it: there is no join to drop, and counting events instead would answer a different
question. So only a subquery the schema built for a join counts.
"""

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext

from posthog.dataclasses import frozen
from posthog.query_scan.tree import iter_and_terms, strip_aliases


@frozen(eq=False)
class PersonsJoinOutcome:
    reads_persons: bool
    unfiltered: bool


def check_persons_join(context: HogQLContext) -> PersonsJoinOutcome:
    selects = context.persons_selects
    if not selects:
        return PersonsJoinOutcome(reads_persons=False, unfiltered=False)
    return PersonsJoinOutcome(
        reads_persons=True,
        unfiltered=any(subquery.from_join and _is_unfiltered(subquery.select) for subquery in selects),
    )


def _is_unfiltered(select: ast.SelectQuery) -> bool:
    """Whether the subquery's ``where`` holds nothing but the version deduplication.

    ``argmax_select`` puts the deleted and created_at housekeeping in ``having``, so an
    unfiltered v1 subquery has no ``where`` at all. The v2 subquery keeps one condition, the
    ``id IN (latest version per id)`` lookup. Every way a filter reaches the subquery adds
    something this test rejects: a lazy-join filter and the ``optimizeJoinedFilters``
    pushdown both add a term, and the v2 filter path adds a ``where`` to the inner select.
    """
    return all(_is_version_dedup(term) for term in iter_and_terms(select.where))


def _is_version_dedup(term: ast.Expr) -> bool:
    term = strip_aliases(term)
    if not isinstance(term, ast.CompareOperation) or term.op != ast.CompareOperationOp.In:
        return False
    right = strip_aliases(term.right)
    return isinstance(right, ast.SelectQuery) and right.where is None
