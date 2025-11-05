import typing
from enum import StrEnum

from django.db import models


class IncrementalFieldType(StrEnum):
    Integer = "integer"
    Numeric = "numeric"  # For snowflake
    DateTime = "datetime"
    Date = "date"
    Timestamp = "timestamp"
    # MongoDB specific
    ObjectID = "objectid"


class IncrementalField(typing.TypedDict):
    label: str  # Label shown in the UI
    type: IncrementalFieldType  # Field type shown in the UI
    field: str  # Actual DB field accessed
    field_type: IncrementalFieldType  # Actual DB type of the field


class PartitionSettings(typing.NamedTuple):
    """Settings used when partitioning data warehouse tables.

    Attributes:
        partition_count: Total number of partitions.
        partition_size: Number of rows to include per partition.
    """

    partition_count: int
    partition_size: int


class ExternalDataSourceType(models.TextChoices):
    CUSTOMERIO = "CustomerIO", "CustomerIO"
    GITHUB = "Github", "Github"
    STRIPE = "Stripe", "Stripe"
    HUBSPOT = "Hubspot", "Hubspot"
    POSTGRES = "Postgres", "Postgres"
    ZENDESK = "Zendesk", "Zendesk"
    SNOWFLAKE = "Snowflake", "Snowflake"
    SALESFORCE = "Salesforce", "Salesforce"
    MYSQL = "MySQL", "MySQL"
    MONGODB = "MongoDB", "MongoDB"
    MSSQL = "MSSQL", "MSSQL"
    VITALLY = "Vitally", "Vitally"
    BIGQUERY = "BigQuery", "BigQuery"
    CHARGEBEE = "Chargebee", "Chargebee"
    GOOGLEADS = "GoogleAds", "GoogleAds"
    TEMPORALIO = "TemporalIO", "TemporalIO"
    DOIT = "DoIt", "DoIt"
    GOOGLESHEETS = "GoogleSheets", "GoogleSheets"
    METAADS = "MetaAds", "MetaAds"
    KLAVIYO = "Klaviyo", "Klaviyo"
    MAILCHIMP = "Mailchimp", "Mailchimp"
    BRAZE = "Braze", "Braze"
    MAILJET = "Mailjet", "Mailjet"
    REDSHIFT = "Redshift", "Redshift"
    POLAR = "Polar", "Polar"
    REVENUECAT = "RevenueCat", "RevenueCat"
    LINKEDINADS = "LinkedinAds", "LinkedinAds"
    REDDITADS = "RedditAds", "RedditAds"
    TIKTOKADS = "TikTokAds", "TikTokAds"
    SHOPIFY = "Shopify", "Shopify"


class DataWarehouseManagedViewSetKind(models.TextChoices):
    REVENUE_ANALYTICS = "revenue_analytics", "Revenue Analytics"
