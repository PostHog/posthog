"""Generated from `posthog/integrations/catalogue.py`. Do not edit by hand.

Run `hogli build:projections --only integration-kinds` after a change to the catalogue. Import
`IntegrationManager` from `posthog.integrations`, not the classes here.
"""

from enum import StrEnum

from posthog.integrations.accessors import (
    AuthAccessor,
    IntegrationManagerBase,
    IntegrationReader,
    KindAccessor,
    OAuthAccessor,
)
from posthog.integrations.enums import AuthType


class IntegrationKind(StrEnum):
    ANTHROPIC = "anthropic"
    APNS = "apns"
    APPLE_ADS = "apple-ads"
    AWS_REDSHIFT = "aws-redshift"
    AWS_S3 = "aws-s3"
    AZURE_BLOB = "azure-blob"
    BING_ADS = "bing-ads"
    CLICKUP = "clickup"
    CUSTOMERIO_APP = "customerio-app"
    CUSTOMERIO_TRACK = "customerio-track"
    CUSTOMERIO_WEBHOOK = "customerio-webhook"
    DATABRICKS = "databricks"
    EMAIL = "email"
    FIREBASE = "firebase"
    GITHUB = "github"
    GITLAB = "gitlab"
    GOOGLE_ADS = "google-ads"
    GOOGLE_ANALYTICS = "google-analytics"
    GOOGLE_CALENDAR = "google-calendar"
    GOOGLE_CLOUD_SERVICE_ACCOUNT = "google-cloud-service-account"
    GOOGLE_CLOUD_STORAGE = "google-cloud-storage"
    GOOGLE_PUBSUB = "google-pubsub"
    GOOGLE_SEARCH_CONSOLE = "google-search-console"
    GOOGLE_SHEETS = "google-sheets"
    HELPSCOUT = "helpscout"
    HUBSPOT = "hubspot"
    INSTAGRAM = "instagram"
    INTERCOM = "intercom"
    JIRA = "jira"
    LINEAR = "linear"
    LINKEDIN_ADS = "linkedin-ads"
    META_ADS = "meta-ads"
    PARDOT = "pardot"
    PINTEREST_ADS = "pinterest-ads"
    POSTGRESQL = "postgresql"
    POSTHOG = "posthog"
    REDDIT_ADS = "reddit-ads"
    RESEND = "resend"
    S3_COMPATIBLE = "s3-compatible"
    SALESFORCE = "salesforce"
    SLACK = "slack"
    SLACK_POSTHOG_CODE = "slack-posthog-code"
    SNAPCHAT = "snapchat"
    SNOWFLAKE = "snowflake"
    STRIPE = "stripe"
    TIKTOK_ADS = "tiktok-ads"
    TWILIO = "twilio"
    TWITTER_ADS = "twitter-ads"
    VERCEL = "vercel"
    YOUTUBE_ANALYTICS = "youtube-analytics"


class AnthropicKind(KindAccessor):
    kind = "anthropic"
    token = AuthAccessor(kind="anthropic", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"anthropic"}))


class ApnsKind(KindAccessor):
    kind = "apns"
    credentials = AuthAccessor(kind="apns", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"apns"}))


class AppleAdsKind(KindAccessor):
    kind = "apple-ads"
    oauth = OAuthAccessor(kind="apple-ads")  # the default
    credentials = AuthAccessor(kind="apple-ads", auth_type=AuthType.CREDENTIALS)
    any = IntegrationReader(kinds=frozenset({"apple-ads"}))


class AwsRedshiftKind(KindAccessor):
    kind = "aws-redshift"
    credentials = AuthAccessor(kind="aws-redshift", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"aws-redshift"}))


class AwsS3Kind(KindAccessor):
    kind = "aws-s3"
    credentials = AuthAccessor(kind="aws-s3", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"aws-s3"}))


class AzureBlobKind(KindAccessor):
    kind = "azure-blob"
    credentials = AuthAccessor(kind="azure-blob", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"azure-blob"}))


class BingAdsKind(KindAccessor):
    kind = "bing-ads"
    oauth = OAuthAccessor(kind="bing-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"bing-ads"}))


class ClickupKind(KindAccessor):
    kind = "clickup"
    oauth = OAuthAccessor(kind="clickup")  # the default
    token = AuthAccessor(kind="clickup", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"clickup"}))


class CustomerioAppKind(KindAccessor):
    kind = "customerio-app"
    token = AuthAccessor(kind="customerio-app", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"customerio-app"}))


class CustomerioTrackKind(KindAccessor):
    kind = "customerio-track"
    token = AuthAccessor(kind="customerio-track", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"customerio-track"}))


class CustomerioWebhookKind(KindAccessor):
    kind = "customerio-webhook"
    token = AuthAccessor(kind="customerio-webhook", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"customerio-webhook"}))


class DatabricksKind(KindAccessor):
    kind = "databricks"
    token = AuthAccessor(kind="databricks", auth_type=AuthType.TOKEN)
    credentials = AuthAccessor(kind="databricks", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"databricks"}))


class EmailKind(KindAccessor):
    kind = "email"
    credentials = AuthAccessor(kind="email", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"email"}))


class FirebaseKind(KindAccessor):
    kind = "firebase"
    credentials = AuthAccessor(kind="firebase", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"firebase"}))


class GithubKind(KindAccessor):
    kind = "github"
    oauth = OAuthAccessor(kind="github")  # the default
    token = AuthAccessor(kind="github", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"github"}))


class GitlabKind(KindAccessor):
    kind = "gitlab"
    token = AuthAccessor(kind="gitlab", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"gitlab"}))


class GoogleAdsKind(KindAccessor):
    kind = "google-ads"
    oauth = OAuthAccessor(kind="google-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"google-ads"}))


class GoogleAnalyticsKind(KindAccessor):
    kind = "google-analytics"
    oauth = OAuthAccessor(kind="google-analytics")  # the default
    any = IntegrationReader(kinds=frozenset({"google-analytics"}))


class GoogleCalendarKind(KindAccessor):
    kind = "google-calendar"
    oauth = OAuthAccessor(kind="google-calendar")  # the default
    any = IntegrationReader(kinds=frozenset({"google-calendar"}))


class GoogleCloudServiceAccountKind(KindAccessor):
    kind = "google-cloud-service-account"
    credentials = AuthAccessor(kind="google-cloud-service-account", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"google-cloud-service-account"}))


class GoogleCloudStorageKind(KindAccessor):
    kind = "google-cloud-storage"
    credentials = AuthAccessor(kind="google-cloud-storage", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"google-cloud-storage"}))


class GooglePubsubKind(KindAccessor):
    kind = "google-pubsub"
    credentials = AuthAccessor(kind="google-pubsub", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"google-pubsub"}))


class GoogleSearchConsoleKind(KindAccessor):
    kind = "google-search-console"
    oauth = OAuthAccessor(kind="google-search-console")  # the default
    any = IntegrationReader(kinds=frozenset({"google-search-console"}))


class GoogleSheetsKind(KindAccessor):
    kind = "google-sheets"
    oauth = OAuthAccessor(kind="google-sheets")  # the default
    credentials = AuthAccessor(kind="google-sheets", auth_type=AuthType.CREDENTIALS)
    any = IntegrationReader(kinds=frozenset({"google-sheets"}))


class HelpscoutKind(KindAccessor):
    kind = "helpscout"
    oauth = OAuthAccessor(kind="helpscout")  # the default
    any = IntegrationReader(kinds=frozenset({"helpscout"}))


class HubspotKind(KindAccessor):
    kind = "hubspot"
    oauth = OAuthAccessor(kind="hubspot")  # the default
    any = IntegrationReader(kinds=frozenset({"hubspot"}))


class InstagramKind(KindAccessor):
    kind = "instagram"
    oauth = OAuthAccessor(kind="instagram")  # the default
    any = IntegrationReader(kinds=frozenset({"instagram"}))


class IntercomKind(KindAccessor):
    kind = "intercom"
    oauth = OAuthAccessor(kind="intercom")  # the default
    any = IntegrationReader(kinds=frozenset({"intercom"}))


class JiraKind(KindAccessor):
    kind = "jira"
    oauth = OAuthAccessor(kind="jira")  # the default
    token = AuthAccessor(kind="jira", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"jira"}))


class LinearKind(KindAccessor):
    kind = "linear"
    oauth = OAuthAccessor(kind="linear")  # the default
    any = IntegrationReader(kinds=frozenset({"linear"}))


class LinkedinAdsKind(KindAccessor):
    kind = "linkedin-ads"
    oauth = OAuthAccessor(kind="linkedin-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"linkedin-ads"}))


class MetaAdsKind(KindAccessor):
    kind = "meta-ads"
    oauth = OAuthAccessor(kind="meta-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"meta-ads"}))


class PardotKind(KindAccessor):
    kind = "pardot"
    oauth = OAuthAccessor(kind="pardot")  # the default
    any = IntegrationReader(kinds=frozenset({"pardot"}))


class PinterestAdsKind(KindAccessor):
    kind = "pinterest-ads"
    oauth = OAuthAccessor(kind="pinterest-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"pinterest-ads"}))


class PostgresqlKind(KindAccessor):
    kind = "postgresql"
    credentials = AuthAccessor(kind="postgresql", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"postgresql"}))


class PosthogKind(KindAccessor):
    kind = "posthog"
    oauth = OAuthAccessor(kind="posthog")  # the default
    any = IntegrationReader(kinds=frozenset({"posthog"}))


class RedditAdsKind(KindAccessor):
    kind = "reddit-ads"
    oauth = OAuthAccessor(kind="reddit-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"reddit-ads"}))


class ResendKind(KindAccessor):
    kind = "resend"
    oauth = OAuthAccessor(kind="resend")  # the default
    token = AuthAccessor(kind="resend", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"resend"}))


class S3CompatibleKind(KindAccessor):
    kind = "s3-compatible"
    credentials = AuthAccessor(kind="s3-compatible", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"s3-compatible"}))


class SalesforceKind(KindAccessor):
    kind = "salesforce"
    oauth = OAuthAccessor(kind="salesforce")  # the default
    any = IntegrationReader(kinds=frozenset({"salesforce"}))


class SlackKind(KindAccessor):
    kind = "slack"
    oauth = OAuthAccessor(kind="slack")  # the default
    token = AuthAccessor(kind="slack", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"slack"}))


class SlackPosthogCodeKind(KindAccessor):
    kind = "slack-posthog-code"
    oauth = OAuthAccessor(kind="slack-posthog-code")  # the default
    any = IntegrationReader(kinds=frozenset({"slack-posthog-code"}))


class SnapchatKind(KindAccessor):
    kind = "snapchat"
    oauth = OAuthAccessor(kind="snapchat")  # the default
    any = IntegrationReader(kinds=frozenset({"snapchat"}))


class SnowflakeKind(KindAccessor):
    kind = "snowflake"
    credentials = AuthAccessor(kind="snowflake", auth_type=AuthType.CREDENTIALS)  # the default
    any = IntegrationReader(kinds=frozenset({"snowflake"}))


class StripeKind(KindAccessor):
    kind = "stripe"
    oauth = OAuthAccessor(kind="stripe")  # the default
    token = AuthAccessor(kind="stripe", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"stripe"}))


class TiktokAdsKind(KindAccessor):
    kind = "tiktok-ads"
    oauth = OAuthAccessor(kind="tiktok-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"tiktok-ads"}))


class TwilioKind(KindAccessor):
    kind = "twilio"
    token = AuthAccessor(kind="twilio", auth_type=AuthType.TOKEN)  # the default
    any = IntegrationReader(kinds=frozenset({"twilio"}))


class TwitterAdsKind(KindAccessor):
    kind = "twitter-ads"
    oauth = OAuthAccessor(kind="twitter-ads")  # the default
    any = IntegrationReader(kinds=frozenset({"twitter-ads"}))


class VercelKind(KindAccessor):
    kind = "vercel"
    oauth = OAuthAccessor(kind="vercel")  # the default
    token = AuthAccessor(kind="vercel", auth_type=AuthType.TOKEN)
    any = IntegrationReader(kinds=frozenset({"vercel"}))


class YoutubeAnalyticsKind(KindAccessor):
    kind = "youtube-analytics"
    oauth = OAuthAccessor(kind="youtube-analytics")  # the default
    any = IntegrationReader(kinds=frozenset({"youtube-analytics"}))


class GeneratedIntegrationManager(IntegrationManagerBase):
    anthropic = AnthropicKind()
    apns = ApnsKind()
    apple_ads = AppleAdsKind()
    aws_redshift = AwsRedshiftKind()
    aws_s3 = AwsS3Kind()
    azure_blob = AzureBlobKind()
    bing_ads = BingAdsKind()
    clickup = ClickupKind()
    customerio_app = CustomerioAppKind()
    customerio_track = CustomerioTrackKind()
    customerio_webhook = CustomerioWebhookKind()
    databricks = DatabricksKind()
    email = EmailKind()
    firebase = FirebaseKind()
    github = GithubKind()
    gitlab = GitlabKind()
    google_ads = GoogleAdsKind()
    google_analytics = GoogleAnalyticsKind()
    google_calendar = GoogleCalendarKind()
    google_cloud_service_account = GoogleCloudServiceAccountKind()
    google_cloud_storage = GoogleCloudStorageKind()
    google_pubsub = GooglePubsubKind()
    google_search_console = GoogleSearchConsoleKind()
    google_sheets = GoogleSheetsKind()
    helpscout = HelpscoutKind()
    hubspot = HubspotKind()
    instagram = InstagramKind()
    intercom = IntercomKind()
    jira = JiraKind()
    linear = LinearKind()
    linkedin_ads = LinkedinAdsKind()
    meta_ads = MetaAdsKind()
    pardot = PardotKind()
    pinterest_ads = PinterestAdsKind()
    postgresql = PostgresqlKind()
    posthog = PosthogKind()
    reddit_ads = RedditAdsKind()
    resend = ResendKind()
    s3_compatible = S3CompatibleKind()
    salesforce = SalesforceKind()
    slack = SlackKind()
    slack_posthog_code = SlackPosthogCodeKind()
    snapchat = SnapchatKind()
    snowflake = SnowflakeKind()
    stripe = StripeKind()
    tiktok_ads = TiktokAdsKind()
    twilio = TwilioKind()
    twitter_ads = TwitterAdsKind()
    vercel = VercelKind()
    youtube_analytics = YoutubeAnalyticsKind()
