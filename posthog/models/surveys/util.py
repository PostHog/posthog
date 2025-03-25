survey_response = "$survey_response"


def get_survey_response_clickhouse_query(question_index: int, question_id: str | None = None) -> str:
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
