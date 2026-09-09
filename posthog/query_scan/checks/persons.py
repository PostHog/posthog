"""Decide whether a query joins the persons table without pushing a filter into it.

``select_from_persons_table`` builds a subquery that deduplicates every person version for
the project. With no filter inside it, that subquery reads every person row on every run, so
a query over a few million events can be dominated by the join.

The records come from ``HogQLContext.persons_selects``, which the schema fills while it builds
each subquery. They carry how the query reached the subquery, because the subquery itself looks
the same for a join and for a read straight from the persons table, and a pushed filter takes a
different shape for each argMax version and pushdown modifier.

A read straight from the persons table is left alone: there is no join to drop, and counting
events instead would answer a different question.
"""

from posthog.hogql.context import HogQLContext

from posthog.dataclasses import frozen


@frozen(eq=False)
class PersonsJoinOutcome:
    reads_persons: bool
    unfiltered: bool


def check_persons_join(context: HogQLContext) -> PersonsJoinOutcome:
    records = context.persons_selects
    return PersonsJoinOutcome(
        reads_persons=any(record.joined for record in records),
        unfiltered=any(record.joined and not record.filtered for record in records),
    )
