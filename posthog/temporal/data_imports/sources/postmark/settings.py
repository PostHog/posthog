from dataclasses import dataclass, field
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

POSTMARK_BASE_URL = "https://api.postmarkapp.com"
POSTMARK_PAGE_SIZE = 500
POSTMARK_DEFAULT_LOOKBACK_DAYS = 30
# Postmark's outbound message search has a hard 45-day window; clamp to stay under it.
POSTMARK_OUTBOUND_MAX_WINDOW_DAYS = 45


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class PostmarkEndpointConfig:
    path: str
    data_key: str
    primary_key: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The Postmark API field that drives `fromdate`/`todate` filtering, e.g. "ReceivedAt".
    # None means the endpoint does not support incremental sync.
    incremental_field_api_name: Optional[str] = None
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = "datetime"
    partition_format: Optional[PartitionFormat] = "month"
    partition_count: int = 1
    partition_size: int = 1
    default_lookback_days: int = POSTMARK_DEFAULT_LOOKBACK_DAYS
    is_paginated: bool = True
    # Some endpoints cap how far back data is retained; we clamp `fromdate` to (now - max_window_days)
    # to avoid pretending we'll backfill older rows that Postmark won't actually return.
    max_window_days: Optional[int] = None
    # Endpoint requires fan-out over message streams (`/message-streams/{id}/...`). When True,
    # `path` is treated as a Python format string with a single `{stream_id}` placeholder; each
    # row yielded is enriched with a `MessageStreamID` field.
    fan_out_streams: bool = False


POSTMARK_ENDPOINTS: dict[str, PostmarkEndpointConfig] = {
    # /messages/outbound (and /opens, /clicks) default to filtering by the "outbound" transactional
    # stream unless `messagestream=` is supplied. Fan out across the account's message streams
    # so we don't silently miss broadcast or custom-stream activity.
    "outbound_messages": PostmarkEndpointConfig(
        path="/messages/outbound",
        data_key="Messages",
        primary_key=["MessageID"],
        incremental_fields=[_datetime_field("ReceivedAt")],
        incremental_field_api_name="ReceivedAt",
        partition_keys=["ReceivedAt"],
        partition_format="month",
        max_window_days=POSTMARK_OUTBOUND_MAX_WINDOW_DAYS,
        fan_out_streams=True,
    ),
    "outbound_opens": PostmarkEndpointConfig(
        path="/messages/outbound/opens",
        data_key="Opens",
        primary_key=["MessageID", "ReceivedAt", "Recipient"],
        incremental_fields=[_datetime_field("ReceivedAt")],
        incremental_field_api_name="ReceivedAt",
        partition_keys=["ReceivedAt"],
        partition_format="day",
        fan_out_streams=True,
    ),
    "outbound_clicks": PostmarkEndpointConfig(
        path="/messages/outbound/clicks",
        data_key="Clicks",
        primary_key=["MessageID", "ReceivedAt", "Recipient"],
        incremental_fields=[_datetime_field("ReceivedAt")],
        incremental_field_api_name="ReceivedAt",
        partition_keys=["ReceivedAt"],
        partition_format="day",
        fan_out_streams=True,
    ),
    "bounces": PostmarkEndpointConfig(
        path="/bounces",
        data_key="Bounces",
        primary_key=["ID"],
        incremental_fields=[_datetime_field("BouncedAt")],
        incremental_field_api_name="BouncedAt",
        partition_keys=["BouncedAt"],
        partition_format="month",
    ),
    "inbound_messages": PostmarkEndpointConfig(
        path="/messages/inbound",
        data_key="InboundMessages",
        primary_key=["MessageID"],
        incremental_fields=[_datetime_field("ReceivedAt")],
        incremental_field_api_name="ReceivedAt",
        partition_keys=["ReceivedAt"],
        partition_format="month",
    ),
    "templates": PostmarkEndpointConfig(
        path="/templates",
        data_key="Templates",
        primary_key=["TemplateId"],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "message_streams": PostmarkEndpointConfig(
        path="/message-streams",
        data_key="MessageStreams",
        primary_key=["ID"],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
        is_paginated=False,
    ),
    # /deliverystats returns a single object with a Bounces[] rollup of bounce-type counts.
    # We yield the Bounces entries as rows; the surrounding `InactiveMails` scalar is dropped
    # for now (derive from the raw `bounces` table if needed).
    "delivery_stats": PostmarkEndpointConfig(
        path="/deliverystats",
        data_key="Bounces",
        primary_key=["Name"],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
        is_paginated=False,
    ),
    # Per-stream suppression dump. The pipeline iterates message-streams and pulls
    # /message-streams/{id}/suppressions/dump for each; rows are enriched with `MessageStreamID`.
    # Postmark's dump endpoint has no server-side incremental filter, so this is full-refresh.
    "suppressions": PostmarkEndpointConfig(
        path="/message-streams/{stream_id}/suppressions/dump",
        data_key="Suppressions",
        primary_key=["MessageStreamID", "EmailAddress"],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
        is_paginated=False,
        fan_out_streams=True,
    ),
}

ENDPOINTS = tuple(POSTMARK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in POSTMARK_ENDPOINTS.items()
}
