ACTION_QUERY = """
SELECT * FROM EVENTS WHERE id IN {action_filter}
"""

# action_filter — concatenation of element_action_filters and event_action_filters

ELEMENT_ACTION_FILTER = """
SELECT id FROM events WHERE 
elements_hash IN (
    SELECT hash FROM element_group WHERE id IN (
        SELECT group_id from elements WHERE id IN
            {element_filter}
    ) 
)
"""

ELEMENT_PROP_FILTER = """
(
    SELECT id FROM elements_properties_view WHERE
    key = {} AND value = {}
)
"""

# element_filter –
#     (
#         SELECT id FROM elements_properties_view WHERE
#         key = 'attr__type' AND value = 'submit'
#     )
#     AND id IN
#     (
#         SELECT id FROM elements_properties_view WHERE
#         key = 'attr__class' AND value = 'btn btn-success'
#     )
#     AND tag_name = 'button'


EVENT_ACTION_FILTER = """
SELECT id from events_with_array_props_view WHERE id IN (
    SELECT event_id
    FROM events_properties_view AS ep
    WHERE team_id = %(team_id)s {property_filter}
) {event_filter}
"""

#####
# event_filter — "event = '$pageview'" or ''
# property_filter — "AND (ep.key = '$browser') AND (ep.value = 'Chrome')" or ''
#####


# example:
# SELECT count(1) FROM events where id IN
# (
#     SELECT id from events where
#     elements_hash IN (
#         SELECT hash from element_group where id IN (
#             SELECT group_id from elements WHERE id IN
#                 (
#                     SELECT id FROM elements_properties_view WHERE
#                     key = 'attr__type' AND value = 'submit'
#                 )
#                 AND id IN
#                 (
#                     SELECT id FROM elements_properties_view WHERE
#                     key = 'attr__class' AND value = 'btn btn-success'
#                 )
#                 AND tag_name = 'button'
#         )
#     ) AND team_id = 2
# )
# OR id IN
# (
#     SELECT id from events_with_array_props_view WHERE id IN (
#         SELECT event_id
#         FROM events_properties_view AS ep
#         WHERE team_id = 2 AND (ep.key = '$browser') AND (ep.value = 'Chrome')
#     )
# )
