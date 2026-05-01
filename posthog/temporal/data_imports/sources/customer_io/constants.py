from typing import Literal, NamedTuple

EMAIL_RESOURCE_NAME = "email_events"
PUSH_RESOURCE_NAME = "push_events"
SMS_RESOURCE_NAME = "sms_events"
IN_APP_RESOURCE_NAME = "in_app_events"
SLACK_RESOURCE_NAME = "slack_events"
WEBHOOK_RESOURCE_NAME = "webhook_events"
CUSTOMER_RESOURCE_NAME = "customer_events"

# Maps PostHog webhook-backed schema name -> Customer.io reporting webhook `object_type`
# value. The webhook payload's `object_type` field is matched against this map's values
# (via `webhook_resource_map` on the source) to route incoming events into the right
# warehouse table. Reporting-webhook docs:
# https://customer.io/docs/journeys/reporting-webhooks/
RESOURCE_TO_CIO_OBJECT_TYPE: dict[str, str] = {
    CUSTOMER_RESOURCE_NAME: "customer",
    EMAIL_RESOURCE_NAME: "email",
    PUSH_RESOURCE_NAME: "push",
    SMS_RESOURCE_NAME: "sms",
    IN_APP_RESOURCE_NAME: "in_app",
    SLACK_RESOURCE_NAME: "slack",
    WEBHOOK_RESOURCE_NAME: "webhook",
}

CIO_WEBHOOK_SCHEMA_NAMES: tuple[str, ...] = tuple(RESOURCE_TO_CIO_OBJECT_TYPE.keys())

# Maps Customer.io `object_type` -> the full set of reporting-webhook event names accepted
# by `POST /v1/reporting_webhooks`. The OpenAPI enum is missing `in_app_*`, but the
# Reporting Webhooks docs (https://docs.customer.io/integrations/data-out/connections/webhooks/)
# document `in_app_sent`, `in_app_clicked`, `in_app_opened`, and `in_app_converted` as
# valid metrics — we include them so users can subscribe to in-app events.
CIO_OBJECT_TYPE_TO_EVENTS: dict[str, tuple[str, ...]] = {
    "customer": (
        "customer_subscribed",
        "customer_unsubscribed",
        "customer_subscription_preferences_changed",
    ),
    "email": (
        "email_drafted",
        "email_attempted",
        "email_sent",
        "email_delivered",
        "email_opened",
        "email_clicked",
        "email_converted",
        "email_bounced",
        "email_dropped",
        "email_deferred",
        "email_spammed",
        "email_failed",
        "email_unsubscribed",
        "email_undeliverable",
    ),
    "push": (
        "push_drafted",
        "push_attempted",
        "push_sent",
        "push_delivered",
        "push_opened",
        "push_clicked",
        "push_converted",
        "push_bounced",
        "push_dropped",
        "push_failed",
        "push_undeliverable",
    ),
    "in_app": (
        "in_app_sent",
        "in_app_opened",
        "in_app_clicked",
        "in_app_converted",
    ),
    "slack": (
        "slack_drafted",
        "slack_attempted",
        "slack_sent",
        "slack_clicked",
        "slack_converted",
        "slack_failed",
    ),
    "sms": (
        "sms_drafted",
        "sms_attempted",
        "sms_sent",
        "sms_delivered",
        "sms_clicked",
        "sms_converted",
        "sms_bounced",
        "sms_failed",
        "sms_undeliverable",
    ),
    "webhook": (
        "webhook_drafted",
        "webhook_attempted",
        "webhook_sent",
        "webhook_clicked",
        "webhook_converted",
        "webhook_failed",
        "webhook_undeliverable",
    ),
}

CIO_US_BASE_URL = "https://api.customer.io"
CIO_EU_BASE_URL = "https://api-eu.customer.io"

# Default name used when auto-creating the reporting webhook in Customer.io.
CIO_AUTO_WEBHOOK_NAME = "PostHog data warehouse"


PartitionMode = Literal["md5", "numerical", "datetime"]
PartitionFormat = Literal["month", "week", "day", "hour"]


class CIOListEndpoint(NamedTuple):
    """Describes how to fetch a single Customer.io App API list endpoint.

    All endpoints listed here are full-refresh GETs returning a JSON object that wraps
    the list under `response_key`. `cursor_param` / `cursor_field` enable cursor-based
    pagination for endpoints that support it; everything else returns the full list in
    one response.

    Every endpoint declares partitioning. Use `datetime` mode (with a partition key
    pointing at a stable creation timestamp) where one is available, and `md5` mode
    (with a stable id/name field) where it isn't. `partition_key` must be a value that
    never changes after a row is written — never `updated_at`.
    """

    path: str
    response_key: str
    primary_keys: list[str]
    partition_keys: list[str]
    partition_mode: PartitionMode
    partition_format: PartitionFormat | None = None
    partition_count: int = 1
    partition_size: int = 1
    cursor_param: str | None = None  # query-param name to send the next-cursor on
    cursor_field: str | None = None  # response field that holds the next cursor
    page_size: int | None = None  # default `limit` to send when cursor pagination is on


def _datetime_endpoint(
    path: str,
    response_key: str,
    partition_key: str,
    *,
    primary_keys: list[str] | None = None,
    cursor_param: str | None = None,
    cursor_field: str | None = None,
    page_size: int | None = None,
) -> CIOListEndpoint:
    return CIOListEndpoint(
        path=path,
        response_key=response_key,
        primary_keys=primary_keys or ["id"],
        partition_keys=[partition_key],
        partition_mode="datetime",
        partition_format="week",
        cursor_param=cursor_param,
        cursor_field=cursor_field,
        page_size=page_size,
    )


def _md5_endpoint(
    path: str,
    response_key: str,
    *,
    primary_keys: list[str] | None = None,
    partition_keys: list[str] | None = None,
    cursor_param: str | None = None,
    cursor_field: str | None = None,
    page_size: int | None = None,
) -> CIOListEndpoint:
    pks = primary_keys or ["id"]
    return CIOListEndpoint(
        path=path,
        response_key=response_key,
        primary_keys=pks,
        partition_keys=partition_keys or pks,
        partition_mode="md5",
        # Matches the convention used by other md5-partitioned sources (e.g. shopify).
        partition_count=200,
        partition_size=1,
        cursor_param=cursor_param,
        cursor_field=cursor_field,
        page_size=page_size,
    )


# All Customer.io App API list endpoints we expose as warehouse tables.
# Reference: https://docs.customer.io/api/app/
#
# `/v1/messages` is intentionally omitted — it overlaps with the webhook event tables
# (`email_events`, `sms_events`, etc.) which already capture per-delivery activity.
#
# Cursor pagination, partition keys, and partition modes were verified against the live
# EU API on 2026-04-29; tables without a stable `created`/`created_at` field fall back
# to md5 partitioning on their natural primary key.
CIO_API_ENDPOINTS: dict[str, CIOListEndpoint] = {
    "broadcasts": _datetime_endpoint(
        path="/v1/broadcasts",
        response_key="broadcasts",
        partition_key="created",
    ),
    "campaigns": _datetime_endpoint(
        path="/v1/campaigns",
        response_key="campaigns",
        partition_key="created",
    ),
    "collections": _datetime_endpoint(
        path="/v1/collections",
        response_key="collections",
        partition_key="created_at",
    ),
    "newsletters": _datetime_endpoint(
        path="/v1/newsletters",
        response_key="newsletters",
        partition_key="created",
        cursor_param="start",
        cursor_field="next",
        page_size=100,
    ),
    "object_types": _md5_endpoint(
        path="/v1/object_types",
        response_key="types",
    ),
    "segments": _datetime_endpoint(
        path="/v1/segments",
        response_key="segments",
        partition_key="created_at",
    ),
    "sender_identities": _md5_endpoint(
        # Verified empirically — the API returns a `next` cursor here even though
        # the published OpenAPI spec doesn't document it.
        path="/v1/sender_identities",
        response_key="sender_identities",
        cursor_param="start",
        cursor_field="next",
        page_size=100,
    ),
    "snippets": _md5_endpoint(
        # Snippets have no `id` field — `name` is the natural key in the Customer.io
        # UI and is unique per workspace.
        path="/v1/snippets",
        response_key="snippets",
        primary_keys=["name"],
    ),
    "subscription_topics": _md5_endpoint(
        path="/v1/subscription_topics",
        response_key="topics",
    ),
    "transactional": _datetime_endpoint(
        path="/v1/transactional",
        response_key="messages",
        partition_key="created_at",
    ),
}

CIO_API_SCHEMA_NAMES: tuple[str, ...] = tuple(CIO_API_ENDPOINTS.keys())
