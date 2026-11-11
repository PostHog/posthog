import enum

from django.apps import apps
from django.db import models


def _fields_with_enum_member_defaults() -> list[str]:
    found = []
    for model in apps.get_models():
        for field in model._meta.get_fields():
            for attribute in ("default", "db_default"):
                value = getattr(field, attribute, None)
                # Django serializes a Choices member by value, and a plain Enum member as an
                # import of the enum's module, so only the plain member pins a module path.
                if isinstance(value, enum.Enum) and not isinstance(value, models.Choices):
                    found.append(
                        f"{model._meta.label}.{field.name} {attribute}={type(value).__qualname__}.{value.name}"
                    )
    return sorted(found)


def test_model_defaults_are_not_plain_enum_members() -> None:
    found = _fields_with_enum_member_defaults()
    assert found == [], (
        "These model fields use a plain Enum member as a default. A migration then imports the "
        "enum's module, and every later migration of the field depends on that path. Pass "
        "MEMBER.value instead (see posthog/enums.py):\n" + "\n".join(found)
    )
