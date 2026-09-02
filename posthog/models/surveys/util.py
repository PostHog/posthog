survey_response = "$survey_response"


def get_survey_response_clickhouse_query(
    question_index: int, question_id: str | None = None, is_multiple_choice: bool = False
) -> str:
    """
    Generate a ClickHouse query to extract survey response based on question index or ID

    Args:
        question_index: Index of the question
        question_id: ID of the question (optional)

    Returns:
        The survey response or empty string if not found
    """
    id_based_key = _build_id_based_key(question_index, question_id)
    index_based_key = _build_index_based_key(question_index)

    if is_multiple_choice is True:
        return _build_multiple_choice_query(id_based_key, index_based_key)

    return _build_coalesce_query(id_based_key, index_based_key)


def _build_id_based_key(question_index: int, question_id: str | None = None) -> str:
    if question_id:
        return f"'{survey_response}_{question_id}'"

    # Extract the ID from the question at the given index in the questions array
    return f"CONCAT('{survey_response}_', JSONExtractString(JSONExtractArrayRaw(properties, '$survey_questions')[{question_index + 1}], 'id'))"


def _build_index_based_key(question_index: int) -> str:
    if question_index == 0:
        return f"{survey_response}"
    return f"{survey_response}_{question_index}"


def _build_coalesce_query(id_based_key: str, index_based_key: str) -> str:
    return f"""COALESCE(
        NULLIF(JSONExtractString(properties, {id_based_key}), ''),
        NULLIF(JSONExtractString(properties, '{index_based_key}'), '')
    )"""


def _build_multiple_choice_query(id_based_key: str, index_based_key: str) -> str:
    return f"""if(
        JSONHas(properties, {id_based_key}) AND length(JSONExtractArrayRaw(properties, {id_based_key})) > 0,
        JSONExtractArrayRaw(properties, {id_based_key}),
        JSONExtractArrayRaw(properties, '{index_based_key}')
    )"""


def filter_survey_sent_events_by_unique_submission(survey_id: str) -> str:
    """
    Generates a SQL condition string to filter 'survey sent' events, ensuring uniqueness based on submission ID.

    This handles two scenarios for identifying relevant 'survey sent' events:
    1. Events recorded before the introduction of `$survey_submission_id`.
    2. The single latest event for each unique `$survey_submission_id` to account for partial responses or updates.

    Args:
        survey_id: The ID of the survey to filter events for.

    Returns:
        A SQL condition string (part of a WHERE clause) filtering event UUIDs.
    """

    query = f"""uuid IN (
            (
                -- Select events without a submission ID (older format)
                SELECT uuid
                FROM events
                WHERE event = 'survey sent'
                  AND JSONExtractString(properties, '$survey_id') = '{survey_id}'
                  AND COALESCE(JSONExtractString(properties, '$survey_submission_id'), '') = ''
            )
            UNION ALL
            (
                -- Select the latest event for each submission ID
                SELECT argMax(uuid, timestamp) -- ClickHouse function to get the arg (uuid) for the max value (timestamp)
                FROM events
                WHERE event = 'survey sent'
                  AND JSONExtractString(properties, '$survey_id') = '{survey_id}'
                  AND COALESCE(JSONExtractString(properties, '$survey_submission_id'), '') != ''
                GROUP BY JSONExtractString(properties, '$survey_submission_id') -- Find the latest event per submission
            )
        )"""
    return query
