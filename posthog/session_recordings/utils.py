import json

from pydantic import ValidationError
from rest_framework import exceptions

from posthog.schema import RecordingsQuery


def clean_prompt_whitespace(prompt: str) -> str:
    """
    Cleans unnecessary whitespace from prompts while preserving single spaces between words.
    Args:
        prompt: The input string to clean
    Returns:
        String with normalized whitespace - single spaces between words, no leading/trailing whitespace
    """
    # Replace multiple spaces with single space and strip leading/trailing whitespace
    return " ".join(prompt.split())


def query_as_params_to_dict(params_dict: dict) -> dict:
    """
    before (if ever) we convert this to a query runner that takes a post
    we need to convert to a valid dict from the data that arrived in query params
    """
    converted = {}
    for key in params_dict:
        try:
            converted[key] = json.loads(params_dict[key]) if isinstance(params_dict[key], str) else params_dict[key]
        except json.JSONDecodeError:
            converted[key] = params_dict[key]

    # we used to accept this value,
    # but very unlikely to receive it now
    # it's safe to pop
    # to make sure any old URLs or filters don't error
    # if they still include it
    converted.pop("as_query", None)

    return converted


def filter_from_params_to_query(params: dict) -> RecordingsQuery:
    data_dict = query_as_params_to_dict(params)
    # we used to send `version` and it's not part of query, so we pop to make sure
    data_dict.pop("version", None)
    # we used to send `hogql_filtering` and it's not part of query, so we pop to make sure
    data_dict.pop("hogql_filtering", None)

    try:
        return RecordingsQuery.model_validate(data_dict)
    except ValidationError as pydantic_validation_error:
        raise exceptions.ValidationError(json.dumps(pydantic_validation_error.errors()))
