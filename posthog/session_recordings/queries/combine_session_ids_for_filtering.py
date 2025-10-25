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
