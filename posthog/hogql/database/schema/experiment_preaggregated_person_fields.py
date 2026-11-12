from posthog.hogql.database.lazy_join_tags import PERSON_DISTINCT_ID_OVERRIDES
from posthog.hogql.database.models import (
    ExpressionField,
    FieldOrTable,
    LazyJoin,
    StringDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.database.schema.person_distinct_id_overrides import PersonDistinctIdOverridesTable
from posthog.hogql.parser import parse_expr


def experiment_preaggregated_person_fields() -> dict[str, FieldOrTable]:
    """
    The fields that resolve a row of an experiment preaggregated table to its current person.

    A row stores the person as of the time the job built it. A later identify or merge moves the
    row's distinct_id to another person, and `person_id` follows that move the way `events.person_id`
    does: it reads `person_distinct_id_overrides` first and falls back to the stored person.

    The override applies for every team instead of following the persons-on-events mode, as in
    `flag_evaluations`. A team on `PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS` therefore reads a
    merge-aware person here, and from `events` the write-time person until the squash rewrites it.

    A row with an empty distinct_id matches no override row, so it keeps its stored person.

    Each table takes its own copy of the fields.
    """
    return {
        "distinct_id": StringDatabaseField(
            name="distinct_id",
            description="Distinct_id of the row's source event; resolves the row to its current person.",
        ),
        "stored_person_id": UUIDDatabaseField(name="person_id", hidden=True),
        # Joined only when a query reads `person_id`, so a group-aggregated read pays nothing for it.
        "override": LazyJoin(
            from_field=["distinct_id"],
            join_table=PersonDistinctIdOverridesTable(),
            resolver=PERSON_DISTINCT_ID_OVERRIDES,
            hidden=True,
        ),
        "person_id": ExpressionField(
            name="person_id",
            expr=parse_expr(
                # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.distinct_id`` is not Nullable
                "if(not(empty(override.distinct_id)), override.person_id, stored_person_id)",
                start=None,
            ),
            isolate_scope=True,
            description="The person the row belongs to, corrected for any later identify or merge. "
            "Meaningful only for person-aggregated experiments.",
        ),
    }
