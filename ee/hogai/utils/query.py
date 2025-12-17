from typing import get_args

from pydantic import ValidationError

from posthog.schema import QuerySchemaRoot

from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, AnyPydanticModelQuery, AssistantSupportedQueryRoot


def is_assistant_query(query: AnyPydanticModelQuery) -> bool:
    return isinstance(query, get_args(AnyAssistantGeneratedQuery))


def validate_assistant_query(query: dict):
    """
    Validates an assistant query and returns the root query object.
    First tries to validate as an assistant query, if that fails, it tries to validate as QuerySchemaRoot.

    Args:
        query: The query to validate.

    Returns:
        The root query object.
    """
    try:
        return AssistantSupportedQueryRoot.model_validate(query).root
    except ValidationError:
        return QuerySchemaRoot.model_validate(query).root
