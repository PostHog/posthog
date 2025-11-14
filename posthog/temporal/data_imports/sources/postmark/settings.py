from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "bounces",
    "messages",
    "message_streams",
    "servers",
    "domains",
    "deliverystats",
)

INCREMENTAL_ENDPOINTS = (
    "bounces",
    "messages",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "bounces": [
        {
            "label": "bounced_at",
            "type": IncrementalFieldType.DateTime,
            "field": "BouncedAt",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "messages": [
        {
            "label": "received_at",
            "type": IncrementalFieldType.DateTime,
            "field": "ReceivedAt",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

PARTITION_FIELDS: dict[str, str] = {
    "bounces": "BouncedAt",
    "messages": "ReceivedAt",
}
