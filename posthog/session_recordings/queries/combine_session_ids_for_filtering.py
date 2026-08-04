from posthog.schema import EventPropertyFilter, FilterLogicalOperator, PropertyOperator, RecordingsQuery


def extract_session_id_property_filter(query: RecordingsQuery) -> RecordingsQuery:
    """
    Pulls an exact-match `$session_id` event-property filter out of `properties` and into
    `session_ids`, so it picks up the date-window bypass already applied to explicitly selected
    session IDs (see `bypass_date_window_for_session_ids` in `SessionRecordingListFromQuery`).

    Property-value autocomplete suggests `$session_id` values from a wider window than the
    recordings list's own default date range. Selecting one and leaving it as a plain event
    property filter would apply that (narrower) date range and hide the very session the search
    surfaced.

    Only safe when every filter is AND'd together — pulling a filter out of an OR group changes
    what the group matches — so this is a no-op for OR queries.
    """
    if query.operand != FilterLogicalOperator.AND_ or not query.properties:
        return query

    session_id_values: list[str] = []
    remaining_properties = []
    for prop in query.properties:
        if (
            isinstance(prop, EventPropertyFilter)
            and prop.key == "$session_id"
            and prop.operator in (PropertyOperator.EXACT, PropertyOperator.IN_)
            and prop.value is not None
        ):
            values = prop.value if isinstance(prop.value, list) else [prop.value]
            session_id_values.extend(str(value) for value in values)
        else:
            remaining_properties.append(prop)

    if not session_id_values:
        return query

    query = query.model_copy(deep=True)
    query.properties = remaining_properties or None
    query.session_ids = combine_session_id_filters(session_id_values, query.session_ids)
    return query


def combine_session_id_filters(
    comment_session_ids: list[str] | None, existing_ids: list[str] | None
) -> list[str] | None:
    """
    In either case `None` means we do not want to filter by that set of session IDs
    an empty list means match 0 sessions

    If both are provided we want the intersection of the two sets

    comment_session_ids are sessions that match a comment text search
    existing_ids are sessions sent in the query, normally members of a collection
    """
    if comment_session_ids is None and existing_ids is None:
        return None

    if comment_session_ids is None and existing_ids is not None:
        return list(set(existing_ids))

    if existing_ids is None and comment_session_ids is not None:
        return list(set(comment_session_ids))

    assert comment_session_ids is not None and existing_ids is not None  # Type narrowing for mypy
    return list(set(comment_session_ids).intersection(set(existing_ids)))
