from enum import StrEnum


class SurveyEventName(StrEnum):
    SHOWN = "survey shown"
    DISMISSED = "survey dismissed"
    SENT = "survey sent"


class SurveyEventProperties(StrEnum):
    SURVEY_ID = "$survey_id"
    SURVEY_RESPONSE = "$survey_response"
    SURVEY_ITERATION = "$survey_iteration"
    SURVEY_PARTIALLY_COMPLETED = "$survey_partially_completed"
    SURVEY_SUBMISSION_ID = "$survey_submission_id"
    SURVEY_RESPONDED = "$survey_responded"
    SURVEY_DISMISSED = "$survey_dismissed"
    SURVEY_COMPLETED = "$survey_completed"


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
        return f"'{SurveyEventProperties.SURVEY_RESPONSE}_{question_id}'"

    # Extract the ID from the question at the given index in the questions array
    return f"CONCAT('{SurveyEventProperties.SURVEY_RESPONSE}_', JSONExtractString(JSONExtractArrayRaw(properties, '$survey_questions')[{question_index + 1}], 'id'))"


def _build_index_based_key(question_index: int) -> str:
    if question_index == 0:
        return f"{SurveyEventProperties.SURVEY_RESPONSE}"
    return f"{SurveyEventProperties.SURVEY_RESPONSE}_{question_index}"


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
    Generates a SQL condition string to filter 'survey sent' events, ensuring uniqueness based on submission ID,
    using an optimized approach with argMax(). Usage with uniqueSurveySubmissionsFilter(survey_id).

    This handles two scenarios for identifying relevant 'survey sent' events:
    1. Events recorded before the introduction of `$survey_submission_id` (submission_id is empty/null):
       All such events are considered unique and will be selected (as they form their own group).
    2. Events with `$survey_submission_id`:
       Only the single latest event (by timestamp) for each unique `$survey_submission_id` is selected.

    Args:
        survey_id: The ID of the survey to filter events for.

    Returns:
        A SQL condition string (part of a WHERE clause) filtering event UUIDs.
        Example: "uuid IN (SELECT argMax(uuid, timestamp) FROM ... GROUP BY ...)"
    """
    # Define the column for submission ID to avoid repetition and enhance readability
    submission_id_col = f"JSONExtractString(properties, '{SurveyEventProperties.SURVEY_SUBMISSION_ID}')"

    # Define the grouping key expression. This determines how events are grouped for deduplication.
    # If $survey_submission_id is present, group by it. Otherwise, group by uuid (making each old event unique).
    grouping_key_expr = (
        f"CASE WHEN COALESCE({submission_id_col}, '') = '' THEN toString(uuid) ELSE {submission_id_col} END"
    )

    query = f"""uuid IN (
        SELECT
            argMax(uuid, timestamp) -- Selects the UUID of the event with the latest timestamp within each group
        FROM events
        WHERE event = '{SurveyEventName.SENT}' -- Filter for 'survey sent' events
          AND JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}') = '{survey_id}' -- Filter for the specific survey
          -- Date range filters from the outer query are intentionally NOT included here.
          -- This ensures we find the globally latest unique submission, which is then
          -- filtered by the outer query's date range.
        GROUP BY {grouping_key_expr} -- Group events by the effective submission identifier
    )"""
    return query


def get_unique_survey_event_uuids_sql_subquery(
    base_conditions_sql: list[str],
    group_by_prefix_expressions: list[str] | None = None,
) -> str:
    """
    Generates a SQL subquery string that returns unique event UUIDs for 'survey sent' events,
    deduplicating based on $survey_submission_id (for new events) or uuid (for older events) using argMax.

    The subquery is intended to be used in a `WHERE uuid IN (...)` clause.

    Args:
        base_conditions_sql: A list of SQL conditions for the WHERE clause of the subquery.
                             Example: ["team_id = %(team_id)s", "timestamp >= '2023-01-01'", "event = 'survey sent'"]
                             Callers should ensure "event = 'survey sent'" is included if that's the target.
        group_by_prefix_expressions: A list of SQL expressions to prefix the GROUP BY clause.
                                     These define the segments within which deduplication occurs.
                                     Example: ['team_id', "JSONExtractString(properties, '$survey_id')"]
                                     If empty, deduplication is based purely on submission ID / UUID across
                                     all events matching base_conditions_sql.

    Returns:
        A string for the SQL subquery, e.g.,
        "(SELECT argMax(uuid, timestamp) FROM events WHERE ... GROUP BY ...)"
    """
    if not base_conditions_sql:
        raise ValueError("base_conditions_sql cannot be empty. Provide at least one condition.")

    if group_by_prefix_expressions is None:
        group_by_prefix_expressions = []

    # Ensure the event filter is present in the base conditions
    if base_conditions_sql.count(f"event = '{SurveyEventName.SENT}'") == 0:
        sql_conditions = [*base_conditions_sql, f"event = '{SurveyEventName.SENT}'"]
    else:
        sql_conditions = base_conditions_sql

    # Always include the survey_id in the group by
    if group_by_prefix_expressions.count(f"JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}')") == 0:
        group_by_prefix_expressions.append(f"JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}')")

    where_clause = " AND ".join(sql_conditions)

    submission_id_col = f"JSONExtractString(properties, '{SurveyEventProperties.SURVEY_SUBMISSION_ID}')"
    deduplication_group_by_key = (
        f"CASE WHEN COALESCE({submission_id_col}, '') = '' THEN toString(uuid) ELSE {submission_id_col} END"
    )

    group_by_clause = ", ".join([*group_by_prefix_expressions, deduplication_group_by_key])

    return f"(SELECT argMax(uuid, timestamp) FROM events WHERE {where_clause} GROUP BY {group_by_clause})"
