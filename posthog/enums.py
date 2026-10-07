"""Labeled enums that work like Django's TextChoices and IntegerChoices, without Django.

A product's facade contract files (``backend/facade/contracts.py`` and ``backend/facade/enums.py``)
must not import Django, so they cannot define a ``models.TextChoices`` class. Define a choices enum
with these bases instead. The class body uses the same syntax:

    class DecisionQuestionType(LabeledStrEnum):
        NOUL = "noul", "Yes or no"
        SCORE = "score"  # the label defaults to "Score", the same rule Django uses

The class has ``choices``, ``values``, ``labels`` and ``names``, and each member has ``label``.
``choices`` holds the same (value, label) pairs that a TextChoices class with the same body holds,
so a conversion from TextChoices changes no migration and no OpenAPI schema.
posthog/openapi/enum_names.py derives the OpenAPI component name from the class name, the same way
it does for a Choices class.

This module imports nothing from Django, which is what the facade contract rule checks. Importing
it still runs posthog/__init__.py, which loads Celery and Django, the same as posthog.dataclasses.

Django special-cases only its own Choices classes, so two rules differ from TextChoices:

- Pass ``X.choices`` to ``choices=`` on a model field or a DRF field. Django rejects the class.
- Pass ``X.MEMBER.value`` to ``default=`` on a model field. The migration writer serializes a
  member as an import of the enum's module, so later migrations of the field depend on that path.
"""

import enum
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast


def _default_label(member_name: str) -> str:
    return member_name.replace("_", " ").title()


class LabeledEnumType(enum.EnumType):
    """Split each ``NAME = value, "label"`` pair before EnumType builds the members.

    This follows django.db.models.enums.ChoicesType, without its Django dependencies.
    """

    def __new__(
        metacls, classname: str, bases: tuple[type, ...], classdict: enum.EnumDict, **kwds: Any
    ) -> "LabeledEnumType":
        if "__empty__" in classdict:
            raise TypeError(f"{classname} defines __empty__, which only Django's Choices classes support.")
        labels: list[str] = []
        for key in classdict.member_names:
            value = classdict[key]
            if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
                value, label = value
            else:
                label = _default_label(key)
            labels.append(label)
            # dict.__setitem__ skips the EnumDict guard against assigning a member name twice.
            dict.__setitem__(classdict, key, value)
        cls = super().__new__(metacls, classname, bases, classdict, **kwds)
        for member, label in zip(cls._labeled_members(), labels):
            member._label_ = label
        enum.unique(cast(type[enum.Enum], cls))
        return cls

    def _labeled_members(cls) -> list[Any]:
        return list(cls.__members__.values())

    @property
    def choices(cls) -> list[tuple[Any, str]]:
        return [(member.value, member._label_) for member in cls._labeled_members()]

    @property
    def values(cls) -> list[Any]:
        return [member.value for member in cls._labeled_members()]

    @property
    def labels(cls) -> list[str]:
        return [member._label_ for member in cls._labeled_members()]

    @property
    def names(cls) -> list[str]:
        return list(cls.__members__)


class LabeledStrEnum(enum.StrEnum, metaclass=LabeledEnumType):
    _value_: str
    _label_: str

    if TYPE_CHECKING:
        # mypy reads _value_ as the type of .value only when the class declares __new__. Without
        # it, .value is typed as the (value, label) tuple from the class body.
        def __new__(cls, value: str) -> Self: ...

        # The metaclass properties return Any values. These give mypy the value type, the same
        # types django-stubs gives TextChoices, so `x in X.values` narrows x.
        choices: ClassVar[list[tuple[str, str]]]
        values: ClassVar[list[str]]

    @property
    def label(self) -> str:
        return self._label_


class LabeledIntEnum(enum.IntEnum, metaclass=LabeledEnumType):
    _value_: int
    _label_: str

    if TYPE_CHECKING:
        # See LabeledStrEnum.
        def __new__(cls, value: int) -> Self: ...

        choices: ClassVar[list[tuple[int, str]]]
        values: ClassVar[list[int]]

    @property
    def label(self) -> str:
        return self._label_
