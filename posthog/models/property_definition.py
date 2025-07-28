from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.models.team import Team
from posthog.models.utils import UniqueConstraintByExpression, UUIDTModel
from posthog.settings.data_stores import CLICKHOUSE_DATABASE


class PropertyType(models.TextChoices):
    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Numeric = "Numeric", "Numeric"
    Boolean = "Boolean", "Boolean"
    Duration = "Duration", "Duration"


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


class PropertyDefinition(UUIDTModel):
    class Type(models.IntegerChoices):
        EVENT = 1, "event"
        PERSON = 2, "person"
        GROUP = 3, "group"
        SESSION = 4, "session"

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="property_definitions",
        related_query_name="team",
    )
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    name = models.CharField(max_length=400)
    is_numerical = models.BooleanField(
        default=False
    )  # whether the property can be interpreted as a number, and therefore used for math aggregation operations

    property_type = models.CharField(max_length=50, choices=PropertyType.choices, blank=True, null=True)

    # :TRICKY: May be null for historical events
    type = models.PositiveSmallIntegerField(default=Type.EVENT, choices=Type.choices)
    # Only populated for `Type.GROUP`
    group_type_index = models.PositiveSmallIntegerField(null=True)

    # DEPRECATED
    property_type_format = models.CharField(
        max_length=50, choices=PropertyFormat.choices, blank=True, null=True
    )  # Deprecated in #8292

    # DEPRECATED
    volume_30_day = models.IntegerField(default=None, null=True)  # Deprecated in #4480

    # DEPRECATED
    # Number of times an insight has been saved with this property in its filter in the last 30 rolling days (computed asynchronously when stars align)
    query_usage_30_day = models.IntegerField(default=None, null=True)

    class Meta:
        indexes = [
            # Index on project_id foreign key
            models.Index(fields=["project"], name="posthog_prop_proj_id_d3eb982d"),
            # This indexes the query in api/property_definition.py
            # :KLUDGE: django ORM typing is off here
            models.Index(
                F("team_id"),
                F("type"),
                Coalesce(F("group_type_index"), -1),
                F("query_usage_30_day").desc(nulls_last=True),
                F("name").asc(),
                name="index_property_def_query",
            ),
            models.Index(
                Coalesce(F("project_id"), F("team_id")),
                F("type"),
                Coalesce(F("group_type_index"), -1),
                F("query_usage_30_day").desc(nulls_last=True),
                F("name").asc(),
                name="index_property_def_query_proj",
            ),
            # creates an index pganalyze identified as missing
            # https://app.pganalyze.com/servers/i35ydkosi5cy5n7tly45vkjcqa/checks/index_advisor/missing_index/15282978
            models.Index(fields=["team_id", "type", "is_numerical"]),
            models.Index(
                Coalesce(F("project_id"), F("team_id")),
                F("type"),
                F("is_numerical"),
                name="posthog_pro_project_3583d2_idx",
            ),
            GinIndex(
                name="index_property_definition_name",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            ),  # To speed up DB-based fuzzy searching
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
                concurrently=True,
                name="posthog_propdef_proj_uniq",
                expression="(coalesce(project_id, team_id), name, type, coalesce(group_type_index, -1))",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"

    # This is a dynamically calculated field in api/property_definition.py. Defaults to `True` here to help serializers.
    def is_seen_on_filtered_events(self) -> None:
        return None


# ClickHouse Table DDL

PROPERTY_DEFINITIONS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`property_definitions`
(
    -- Team and project relationships
    team_id UInt32,
    project_id UInt32 NULL,

    -- Core property fields
    name String,
    property_type String NULL,
    event String NULL, -- Only null for non-event types
    group_type_index UInt8 NULL,

    -- Type enum (1=event, 2=person, 3=group, 4=session)
    type UInt8 DEFAULT 1,

    -- Metadata
    last_seen_at DateTime,

    -- A composite version number that prioritizes property_type presence over timestamp
    -- We negate isNull() so rows WITH property_type get higher preference
    version UInt64 MATERIALIZED (bitShiftLeft(toUInt64(NOT isNull(property_type)), 48) + toUInt64(toUnixTimestamp(last_seen_at)))
)
ENGINE = {ReplacingMergeTree("property_definitions", replication_scheme=ReplicationScheme.REPLICATED, ver="version")}
ORDER BY (team_id, type, COALESCE(event, ''), name, COALESCE(group_type_index, 255))
SETTINGS index_granularity = 8192
"""
)

DROP_PROPERTY_DEFINITIONS_TABLE_SQL = lambda: f"DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.`property_definitions`"
