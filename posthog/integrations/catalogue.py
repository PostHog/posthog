"""The integration kinds and the auth types that each kind supports.

This is the hand-written source of `kinds_generated.py`. After a change here, run
`hogli build:projections --only integration-kinds` and commit the result. A kind also needs a value
in `Integration.IntegrationKind` (`posthog/models/integration/model.py`); a test compares the two.

A row stores its auth type in `config["auth_type"]` only when it is not the default of its kind, so
the default of a kind is stored data. Do not change the default of a kind that has rows.

Warehouse source kinds are not in this file. The warehouse product registers them at startup with
`register_source_kinds`.
"""

from collections.abc import Mapping

from posthog.integrations.contracts import KindSpec
from posthog.integrations.enums import AuthType

_OAUTH = AuthType.OAUTH
_TOKEN = AuthType.TOKEN
_CREDENTIALS = AuthType.CREDENTIALS

KINDS: Mapping[str, KindSpec] = {
    "anthropic": KindSpec(label="Anthropic", default=_TOKEN),
    "apns": KindSpec(label="Apple Push Notification service", default=_CREDENTIALS),
    "apple-ads": KindSpec(label="Apple Ads", default=_OAUTH, others=frozenset({_CREDENTIALS})),
    "aws-redshift": KindSpec(label="Amazon Redshift", default=_CREDENTIALS),
    "aws-s3": KindSpec(label="Amazon S3", default=_CREDENTIALS),
    "azure-blob": KindSpec(label="Azure Blob Storage", default=_CREDENTIALS),
    "bing-ads": KindSpec(label="Bing Ads", default=_OAUTH),
    "clickup": KindSpec(label="ClickUp", default=_OAUTH, others=frozenset({_TOKEN})),
    "customerio-app": KindSpec(label="Customer.io App API", default=_TOKEN),
    "customerio-track": KindSpec(label="Customer.io Track API", default=_TOKEN),
    "customerio-webhook": KindSpec(label="Customer.io webhook", default=_TOKEN),
    "databricks": KindSpec(label="Databricks", default=_CREDENTIALS, others=frozenset({_TOKEN})),
    "email": KindSpec(label="Email", default=_CREDENTIALS),
    "firebase": KindSpec(label="Firebase", default=_CREDENTIALS),
    "github": KindSpec(label="GitHub", default=_OAUTH, others=frozenset({_TOKEN})),
    "gitlab": KindSpec(label="GitLab", default=_TOKEN),
    "google-ads": KindSpec(label="Google Ads", default=_OAUTH),
    "google-analytics": KindSpec(label="Google Analytics", default=_OAUTH),
    "google-calendar": KindSpec(label="Google Calendar", default=_OAUTH),
    "google-cloud-service-account": KindSpec(label="Google Cloud service account", default=_CREDENTIALS),
    "google-cloud-storage": KindSpec(label="Google Cloud Storage", default=_CREDENTIALS),
    "google-pubsub": KindSpec(label="Google Pub/Sub", default=_CREDENTIALS),
    "google-search-console": KindSpec(label="Google Search Console", default=_OAUTH),
    "google-sheets": KindSpec(label="Google Sheets", default=_OAUTH, others=frozenset({_CREDENTIALS})),
    "helpscout": KindSpec(label="Help Scout", default=_OAUTH),
    "hubspot": KindSpec(label="HubSpot", default=_OAUTH),
    "instagram": KindSpec(label="Instagram", default=_OAUTH),
    "intercom": KindSpec(label="Intercom", default=_OAUTH),
    "jira": KindSpec(label="Jira", default=_OAUTH, others=frozenset({_TOKEN})),
    "linear": KindSpec(label="Linear", default=_OAUTH),
    "linkedin-ads": KindSpec(label="LinkedIn Ads", default=_OAUTH),
    "meta-ads": KindSpec(label="Meta Ads", default=_OAUTH),
    "pardot": KindSpec(label="Pardot", default=_OAUTH),
    "pinterest-ads": KindSpec(label="Pinterest Ads", default=_OAUTH),
    "postgresql": KindSpec(label="PostgreSQL", default=_CREDENTIALS),
    "posthog": KindSpec(label="PostHog", default=_OAUTH),
    "reddit-ads": KindSpec(label="Reddit Ads", default=_OAUTH),
    "resend": KindSpec(label="Resend", default=_OAUTH, others=frozenset({_TOKEN})),
    "s3-compatible": KindSpec(label="S3-compatible storage", default=_CREDENTIALS),
    "salesforce": KindSpec(label="Salesforce", default=_OAUTH),
    "slack": KindSpec(label="Slack", default=_OAUTH, others=frozenset({_TOKEN})),
    "slack-posthog-code": KindSpec(label="Slack (PostHog Code)", default=_OAUTH),
    "snapchat": KindSpec(label="Snapchat", default=_OAUTH),
    "snowflake": KindSpec(label="Snowflake", default=_CREDENTIALS),
    "stripe": KindSpec(label="Stripe", default=_OAUTH, others=frozenset({_TOKEN})),
    "tiktok-ads": KindSpec(label="TikTok Ads", default=_OAUTH),
    "twilio": KindSpec(label="Twilio", default=_TOKEN),
    "twitter-ads": KindSpec(label="X Ads", default=_OAUTH),
    "vercel": KindSpec(label="Vercel", default=_OAUTH, others=frozenset({_TOKEN})),
    "youtube-analytics": KindSpec(label="YouTube Analytics", default=_OAUTH),
}
