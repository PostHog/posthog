from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.models.team import Team
from posthog.models.utils import UniqueConstraintByExpression, UUIDModel


class PropertyType(models.TextChoices):
    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Numeric = "Numeric", "Numeric"
    Boolean = "Boolean", "Boolean"


class PropertyFormat(models.TextChoices):
    UnixTimestamp = "unix_timestamp", "Unix Timestamp in seconds"
    UnixTimestampMilliseconds = (
        "unix_timestamp_milliseconds",
        "Unix Timestamp in milliseconds",
    )
    ISO8601Date = "YYYY-MM-DDThh:mm:ssZ", "YYYY-MM-DDThh:mm:ssZ"
    FullDate = "YYYY-MM-DD hh:mm:ss", "YYYY-MM-DD hh:mm:ss"
    FullDateIncreasing = "DD-MM-YYYY hh:mm:ss", "DD-MM-YYYY hh:mm:ss"
    Date = "YYYY-MM-DD", "YYYY-MM-DD"
    RFC822 = "rfc_822", "day, DD MMM YYYY hh:mm:ss TZ"
    WithSlashes = "YYYY/MM/DD hh:mm:ss", "YYYY/MM/DD hh:mm:ss"
    WithSlashesIncreasing = "DD/MM/YYYY hh:mm:ss", "DD/MM/YYYY hh:mm:ss"


class PropertyDefinition(UUIDModel):
    class Type(models.IntegerChoices):
        EVENT = 1, "event"
        PERSON = 2, "person"
        GROUP = 3, "group"

    team: models.ForeignKey = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="property_definitions",
        related_query_name="team",
    )
    name: models.CharField = models.CharField(max_length=400)
    is_numerical: models.BooleanField = models.BooleanField(
        default=False
    )  # whether the property can be interpreted as a number, and therefore used for math aggregation operations

    property_type = models.CharField(max_length=50, choices=PropertyType.choices, blank=True, null=True)

    # :TRICKY: May be null for historical events
    type: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(default=Type.EVENT, choices=Type.choices)
    # Only populated for `Type.GROUP`
    group_type_index: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(null=True)

    # DEPRECATED
    property_type_format = models.CharField(
        max_length=50, choices=PropertyFormat.choices, blank=True, null=True
    )  # Deprecated in #8292

    # DEPRECATED
    volume_30_day: models.IntegerField = models.IntegerField(default=None, null=True)  # Deprecated in #4480

    # DEPRECATED
    # Number of times an insight has been saved with this property in its filter in the last 30 rolling days (computed asynchronously when stars align)
    query_usage_30_day: models.IntegerField = models.IntegerField(default=None, null=True)

    class Meta:
        indexes = [
            # This indexes the query in api/property_definition.py
            # :KLUDGE: django ORM typing is off here
            models.Index(  # type: ignore
                F("team_id"),  # type: ignore
                F("type"),  # type: ignore
                Coalesce(F("group_type_index"), -1),  # type: ignore
                F("query_usage_30_day").desc(nulls_last=True),  # type: ignore
                F("name").asc(),  # type: ignore
                name="index_property_def_query",
            ),
            # creates an index pganalyze identified as missing
            # https://app.pganalyze.com/servers/i35ydkosi5cy5n7tly45vkjcqa/checks/index_advisor/missing_index/15282978
            models.Index(fields=["team_id", "type", "is_numerical"]),
        ] + [
            GinIndex(
                name="index_property_definition_name",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            )  # To speed up DB-based fuzzy searching
        ]
        constraints = [
            models.CheckConstraint(
                name="property_type_is_valid",
                check=models.Q(property_type__in=PropertyType.values),
            ),
            models.CheckConstraint(
                name="group_type_index_set",
                check=~models.Q(type=3) | models.Q(group_type_index__isnull=False),
            ),
            UniqueConstraintByExpression(
                name="posthog_propertydefinition_uniq",
                expression="(team_id, name, type, coalesce(group_type_index, -1))",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"

    # This is a dynamically calculated field in api/property_definition.py. Defaults to `True` here to help serializers.
    def is_seen_on_filtered_events(self) -> None:
        return None
