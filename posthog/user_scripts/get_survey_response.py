#!/usr/bin/env python3
"""
Get Survey Response - User Defined Function (UDF) for HogQL/ClickHouse

This script extracts survey responses from the properties JSON of events.
It supports multiple survey question/response formats:

1. Old format: Survey questions as array of strings
   - Responses are stored as $survey_response (first question) or $survey_response_N (index-based)

2. New format: Survey questions as array of dictionaries with id, index, and name
   - Responses are stored as $survey_response_ID (id-based) or fallback to index-based

Usage in HogQL:
    SELECT
        get_survey_response(properties, 0, '') AS first_question_response,
        get_survey_response(properties, 1, '') AS second_question_response,
        get_survey_response(properties, -1, 'specific_id') AS response_by_id
    FROM events
    WHERE event = 'survey sent'

Input:
    - properties: JSON string containing the event properties
    - question_index: Index of the question (int)
    - question_id: ID of the question (string, optional)

Output:
    JSON with "result" field containing the survey response or empty string if not found
"""

import sys
import json
import traceback


def get_question_id_from_survey_questions(survey_questions, question_index):
    """
    Extract question ID from survey_questions array if possible

    Args:
        survey_questions: Array of questions (either strings or dictionaries)
        question_index: Index of the question to extract ID from

    Returns:
        question_id: The ID of the question or None if not available
    """
    # Check if index is valid and question is in dict format
    if (
        len(survey_questions) > question_index
        and isinstance(survey_questions[question_index], dict)
        and "id" in survey_questions[question_index]
    ):
        return survey_questions[question_index]["id"]
    return None


def get_response_from_properties(properties, question_id, question_index):
    """
    Extract response from properties using either ID-based or index-based keys

    Args:
        properties: Dictionary of event properties
        question_id: ID of the question
        question_index: Index of the question

    Returns:
        response: The survey response or empty string if not found
    """
    # ID-based lookup (preferred if ID is available)
    if question_id:
        id_based_key = f"$survey_response_{question_id}"
        if id_based_key in properties:
            return {"result": properties[id_based_key]}

    # Index-based lookup
    # For first question (index 0), key is simply "$survey_response"
    index_based_key = "$survey_response" if question_index == 0 else f"$survey_response_{question_index}"
    if index_based_key in properties:
        return {"result": properties[index_based_key]}

    # No response found
    return {"result": ""}


def process_input_line(line):
    """Process a single input line from stdin"""
    value = json.loads(line)
    properties_json = value["properties"]
    question_index = int(value["question_index"])
    question_id = value["question_id"]

    # Parse the properties JSON string
    properties = json.loads(properties_json)

    # If no question_id was provided, try to extract it from survey_questions
    if not question_id:
        survey_questions = properties.get("$survey_questions", [])
        extracted_id = get_question_id_from_survey_questions(survey_questions, question_index)
        if extracted_id:
            question_id = extracted_id

    # Get the response using either ID-based or index-based lookup
    return get_response_from_properties(properties, question_id, question_index)


def main():
    """Main function to process input and produce output"""
    try:
        for line in sys.stdin:
            result = process_input_line(line)
            print(json.dumps(result), end="\n")  # noqa: T201
            sys.stdout.flush()
    except Exception as e:
        # Log error to stderr
        print(f"Error: {str(e)}", file=sys.stderr)  # noqa: T201
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)  # Exit with non-zero code on error


if __name__ == "__main__":
    main()
