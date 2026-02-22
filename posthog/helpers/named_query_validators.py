import re

from django.core.exceptions import ValidationError


def validate_named_query_name(value: str) -> None:
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", value):
        raise ValidationError(
            f"{value} is not a valid query name. Query names must start with a letter and contain only letters, numbers, hyphens, and underscores.",
            params={"value": value},
        )

    if len(value) > 128:
        raise ValidationError(
            f"Query name '{value}' is too long. Maximum length is 128 characters.",
            params={"value": value},
        )
