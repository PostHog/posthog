FUNNEL_PERSONS_BY_STEP_SQL = """
SELECT aggregation_target AS actor_id{matching_events_select_statement} {extra_fields}
FROM (
    {steps_per_person_query}
)
WHERE {persons_steps}
ORDER BY aggregation_target
{limit}
{offset}
SETTINGS max_ast_elements=1000000, max_expanded_ast_elements=1000000
"""
