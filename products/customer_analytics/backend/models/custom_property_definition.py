from enum import StrEnum

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class DisplayType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    CURRENCY = "currency"
    PERCENT = "percent"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    SELECT = "select"


class DataType(StrEnum):
    STRING = "string"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    DATETIME = "datetime"


DATA_TYPE_BY_DISPLAY_TYPE: dict[DisplayType, DataType] = {
    DisplayType.TEXT: DataType.STRING,
    DisplayType.NUMBER: DataType.NUMERIC,
    DisplayType.CURRENCY: DataType.NUMERIC,
    DisplayType.PERCENT: DataType.NUMERIC,
    DisplayType.DATE: DataType.DATETIME,
    DisplayType.DATETIME: DataType.DATETIME,
    DisplayType.BOOLEAN: DataType.BOOLEAN,
    DisplayType.SELECT: DataType.STRING,
}

NUMERIC_DISPLAY_TYPES = [
    display_type.value for display_type, data_type in DATA_TYPE_BY_DISPLAY_TYPE.items() if data_type == DataType.NUMERIC
]


class CustomPropertyDefinition(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    name = models.CharField(max_length=400)
    description = models.TextField(null=True)
    display_type = models.CharField(
        choices=[(t.value, t.value) for t in DisplayType], default=DisplayType.TEXT, max_length=20
    )
    is_big_number = models.BooleanField(
        default=False, help_text="Whether the property is a big number and should be abbreviated. E.g.: 10,000 -> 10K"
    )
    options = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="For select properties: the allowed options, each {'id', 'label', 'color'}. Null for other types.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_custom_property_per_team",
            ),
            models.CheckConstraint(
                condition=models.Q(is_big_number=False) | models.Q(display_type__in=NUMERIC_DISPLAY_TYPES),
                name="is_big_number_requires_numeric_display_type",
            ),
        ]

    @property
    def data_type(self) -> DataType:
        return DATA_TYPE_BY_DISPLAY_TYPE[DisplayType(self.display_type)]
