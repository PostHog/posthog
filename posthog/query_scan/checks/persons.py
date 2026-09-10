"""Decide whether a query joins the persons table without pushing a filter into it.

``select_from_persons_table`` builds a subquery that deduplicates every person version for the
project. With no filter inside it, that subquery reads every person row on every run, so the join
can dominate a query over a few million events.

A read straight from the persons table is left alone, because there is no join to drop.
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
