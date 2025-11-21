from .common.registry import SourceRegistry

# A lot of these sources use heavy packages, so load them dynamically instead of at startup time

__all__ = [
    "SourceRegistry",
    # Keep these for backwards compatibility, but they'll trigger dynamic imports
    "CustomerIOSource",
    "GithubSource",
    "BigQuerySource",
    "BingAdsSource",
    "BrazeSource",
    "ChargebeeSource",
    "DoItSource",
    "GoogleAdsSource",
    "GoogleSheetsSource",
    "HubspotSource",
    "KlaviyoSource",
    "LinkedInAdsSource",
    "MailchimpSource",
    "MailJetSource",
    "MetaAdsSource",
    "MongoDBSource",
    "RedditAdsSource",
    "MSSQLSource",
    "MySQLSource",
    "PolarSource",
    "PostgresSource",
    "RedshiftSource",
    "TikTokAdsSource",
    "RevenueCatSource",
    "SalesforceSource",
    "ShopifySource",
    "SnowflakeSource",
    "StripeSource",
    "TemporalIOSource",
    "VitallySource",
    "ZendeskSource",
]


def __getattr__(name: str):
    """Dynamically import source classes when accessed"""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Map class names to ExternalDataSourceType values
    from products.data_warehouse.backend.types import ExternalDataSourceType

    # Remove "Source" suffix and convert to enum
    source_name = name[:-6] if name.endswith("Source") else name

    # Map class names to enum values
    name_to_enum = {
        "CustomerIO": ExternalDataSourceType.CUSTOMERIO,
        "Github": ExternalDataSourceType.GITHUB,
        "BigQuery": ExternalDataSourceType.BIGQUERY,
        "BingAds": ExternalDataSourceType.BINGADS,
        "Braze": ExternalDataSourceType.BRAZE,
        "Chargebee": ExternalDataSourceType.CHARGEBEE,
        "DoIt": ExternalDataSourceType.DOIT,
        "GoogleAds": ExternalDataSourceType.GOOGLEADS,
        "GoogleSheets": ExternalDataSourceType.GOOGLESHEETS,
        "Hubspot": ExternalDataSourceType.HUBSPOT,
        "Klaviyo": ExternalDataSourceType.KLAVIYO,
        "LinkedInAds": ExternalDataSourceType.LINKEDINADS,
        "Mailchimp": ExternalDataSourceType.MAILCHIMP,
        "MailJet": ExternalDataSourceType.MAILJET,
        "MetaAds": ExternalDataSourceType.METAADS,
        "MongoDB": ExternalDataSourceType.MONGODB,
        "RedditAds": ExternalDataSourceType.REDDITADS,
        "MSSQL": ExternalDataSourceType.MSSQL,
        "MySQL": ExternalDataSourceType.MYSQL,
        "Polar": ExternalDataSourceType.POLAR,
        "Postgres": ExternalDataSourceType.POSTGRES,
        "Redshift": ExternalDataSourceType.REDSHIFT,
        "TikTokAds": ExternalDataSourceType.TIKTOKADS,
        "RevenueCat": ExternalDataSourceType.REVENUECAT,
        "Salesforce": ExternalDataSourceType.SALESFORCE,
        "Shopify": ExternalDataSourceType.SHOPIFY,
        "Snowflake": ExternalDataSourceType.SNOWFLAKE,
        "Stripe": ExternalDataSourceType.STRIPE,
        "TemporalIO": ExternalDataSourceType.TEMPORALIO,
        "Vitally": ExternalDataSourceType.VITALLY,
        "Zendesk": ExternalDataSourceType.ZENDESK,
    }

    source_type = name_to_enum.get(source_name)
    if source_type is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Get the source instance and return its class
    source_instance = SourceRegistry.get_source(source_type)
    return type(source_instance)
