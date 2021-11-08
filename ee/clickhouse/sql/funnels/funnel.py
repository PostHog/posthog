FUNNEL_PERSONS_BY_STEP_SQL = """
SELECT aggregation_target as person_id {extra_fields}
FROM (
    {steps_per_person_query}
)
WHERE {persons_steps}
ORDER BY aggregation_target
{limit}
OFFSET {offset}
SETTINGS allow_experimental_window_functions = 1
"""

FUNNEL_INNER_EVENT_STEPS_QUERY = """
SELECT 
aggregation_target,
timestamp,
{steps}
{select_prop}
FROM (
    {event_query}
) events
{extra_join}
WHERE (
    {steps_condition}
)
{extra_conditions}
"""
