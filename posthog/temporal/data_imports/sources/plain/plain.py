from datetime import UTC, datetime
from typing import Any

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.plain.queries import (
    QUERIES,
    THREADS_LIST_QUERY,
    TIMELINE_ENTRIES_QUERY,
    VIEWER_QUERY,
)
from posthog.temporal.data_imports.sources.plain.settings import PLAIN_API_URL, PLAIN_DEFAULT_PAGE_SIZE, PLAIN_ENDPOINTS


class PlainRetryableError(Exception):
    pass


_MESSAGE_INFO_FIELDS: list[tuple[str, str]] = [
    ("firstInboundMessageInfo", "firstInboundMessageAt"),
    ("firstOutboundMessageInfo", "firstOutboundMessageAt"),
    ("lastInboundMessageInfo", "lastInboundMessageAt"),
    ("lastOutboundMessageInfo", "lastOutboundMessageAt"),
]


def _datetime_to_plain_iso8601(value: datetime) -> str:
    """Serialize a datetime to the ISO-8601 format Plain returns and accepts (e.g. 2024-01-15T10:30:00.000Z)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _parse_plain_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return parser.parse(value)


def _flatten_datetime(obj: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested datetime objects with iso8601 fields."""
    result = {}
    for key, value in obj.items():
        if isinstance(value, dict):
            if "iso8601" in value and len(value) == 1:
                result[key] = value["iso8601"]
            else:
                result[key] = _flatten_datetime(value)
        elif isinstance(value, list):
            result[key] = [_flatten_datetime(item) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
    return result


def _flatten_node(node: dict[str, Any]) -> dict[str, Any]:
    """Flatten a node, extracting datetime fields and nested objects."""
    flattened = _flatten_datetime(node)

    if "email" in flattened and isinstance(flattened["email"], dict):
        email_obj = flattened.pop("email")
        flattened["email"] = email_obj.get("email")
        flattened["emailIsVerified"] = email_obj.get("isVerified")

    if "customer" in flattened and isinstance(flattened["customer"], dict):
        customer = flattened.pop("customer")
        flattened["customerId"] = customer.get("id")
        flattened["customerFullName"] = customer.get("fullName")
        if isinstance(customer.get("email"), dict):
            flattened["customerEmail"] = customer["email"].get("email")
        else:
            flattened["customerEmail"] = customer.get("email")

    if "assignedToUser" in flattened and isinstance(flattened["assignedToUser"], dict):
        user = flattened.pop("assignedToUser")
        flattened["assignedToUserId"] = user.get("id") if user else None
        flattened["assignedToUserName"] = user.get("fullName") if user else None
        flattened["assignedToUserEmail"] = user.get("email") if user else None

    if "company" in flattened and isinstance(flattened["company"], dict):
        company = flattened.pop("company")
        flattened["companyId"] = company.get("id") if company else None
        flattened["companyName"] = company.get("name") if company else None

    if "labels" in flattened and isinstance(flattened["labels"], list):
        labels = flattened.pop("labels")
        flattened["labelIds"] = [label.get("id") for label in labels if label]
        flattened["labelNames"] = [
            label.get("labelType", {}).get("name") for label in labels if label and label.get("labelType")
        ]

    for actor_field in ["createdBy", "updatedBy", "statusChangedBy", "markedAsSpamBy", "actor"]:
        if actor_field in flattened and isinstance(flattened[actor_field], dict):
            actor = flattened.pop(actor_field)
            flattened[f"{actor_field}Type"] = actor.get("actorType")
            flattened[f"{actor_field}Id"] = (
                actor.get("userId") or actor.get("machineUserId") or actor.get("customerId") or actor.get("systemId")
            )

    for src_field, dst_field in _MESSAGE_INFO_FIELDS:
        if src_field in flattened:
            info = flattened.pop(src_field)
            flattened[dst_field] = info.get("timestamp") if info else None

    return flattened


def _flatten_timeline_entry(entry: dict[str, Any], thread_id: str) -> dict[str, Any]:
    """Flatten a timeline entry node."""
    flattened = _flatten_datetime(entry)
    flattened["threadId"] = thread_id

    if "actor" in flattened and isinstance(flattened["actor"], dict):
        actor = flattened.pop("actor")
        flattened["actorType"] = actor.get("actorType")
        flattened["actorId"] = (
            actor.get("userId") or actor.get("machineUserId") or actor.get("customerId") or actor.get("systemId")
        )

    if "timestamp" in flattened:
        flattened["createdAt"] = flattened.pop("timestamp")

    if "entry" in flattened and isinstance(flattened["entry"], dict):
        entry_data = flattened.pop("entry")
        flattened["entryType"] = entry_data.get("__typename")

        if entry_data.get("__typename") == "ChatEntry":
            flattened["chatId"] = entry_data.get("chatId")
            flattened["text"] = entry_data.get("text")
        elif entry_data.get("__typename") == "EmailEntry":
            flattened["emailId"] = entry_data.get("emailId")
            flattened["subject"] = entry_data.get("subject")
            flattened["text"] = entry_data.get("textContent")
            if entry_data.get("to"):
                flattened["toEmail"] = entry_data["to"].get("email")
                flattened["toName"] = entry_data["to"].get("name")
            if entry_data.get("from"):
                flattened["fromEmail"] = entry_data["from"].get("email")
                flattened["fromName"] = entry_data["from"].get("name")
        elif entry_data.get("__typename") == "NoteEntry":
            flattened["noteId"] = entry_data.get("noteId")
            flattened["text"] = entry_data.get("text")
        elif entry_data.get("__typename") == "CustomTimelineEntry":
            flattened["customEntryId"] = entry_data.get("customTimelineEntryId")
            flattened["title"] = entry_data.get("title")
            flattened["externalId"] = entry_data.get("externalId")

    return flattened


def _make_paginated_request(
    api_key: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    incremental_since: datetime | None = None,
):
    endpoint_config = PLAIN_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Plain endpoint: {endpoint_name}")

    query = QUERIES.get(endpoint_name)
    if not query:
        raise ValueError(f"No GraphQL query for endpoint: {endpoint_name}")

    sess = requests.Session()
    sess.headers.update(
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )

    @retry(
        retry=retry_if_exception_type(PlainRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def execute(query_str: str, variables: dict[str, Any]) -> dict:
        response = sess.post(PLAIN_API_URL, json={"query": query_str, "variables": variables}, timeout=60)

        if response.status_code >= 500:
            raise PlainRetryableError(f"Plain: server error {response.status_code}")

        if response.status_code == 429:
            raise PlainRetryableError("Plain: rate limited")

        try:
            payload = response.json()
        except Exception:
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (Plain API: {response.text})")
            raise Exception(f"Unexpected Plain response: {response.text}")

        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"]]
            joined = "; ".join(error_messages)
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (Plain API: {joined})")
            raise Exception(f"Plain GraphQL error: {joined}")

        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} (Plain API: {payload})")

        if "data" not in payload:
            raise Exception(f"Unexpected Plain response format. Keys: {list(payload.keys())}")

        return payload

    try:
        if endpoint_name == "timeline_entries":
            yield from _fetch_timeline_entries(execute, logger, incremental_since)
        else:
            yield from _fetch_paginated_endpoint(execute, endpoint_name, query, logger, incremental_since)
    finally:
        sess.close()


def _fetch_paginated_endpoint(
    execute,
    endpoint_name: str,
    query: str,
    logger: FilteringBoundLogger,
    updated_at_gte: datetime | None = None,
):
    variables: dict[str, Any] = {"first": PLAIN_DEFAULT_PAGE_SIZE}

    if updated_at_gte is not None:
        variables["filter"] = {"updatedAt": {"gte": _datetime_to_plain_iso8601(updated_at_gte)}}

    has_next_page = True
    while has_next_page:
        logger.debug(f"Querying Plain endpoint {endpoint_name} with variables: {variables}")
        payload = execute(query, variables)

        data = payload["data"][endpoint_name]
        edges = data.get("edges", [])
        nodes = [_flatten_node(edge["node"]) for edge in edges]

        if nodes:
            yield nodes

        page_info = data["pageInfo"]
        has_next_page = page_info["hasNextPage"]
        if has_next_page:
            variables["after"] = page_info["endCursor"]


def _fetch_timeline_entries(
    execute,
    logger: FilteringBoundLogger,
    created_at_gte: datetime | None = None,
):
    """Stream timeline entries page-by-page, yielding entries for each thread as its ID is discovered.

    When ``created_at_gte`` is set, a server-side ``ThreadsFilter`` limits the scan to threads
    updated since that timestamp so incremental syncs avoid enumerating every thread.
    """
    variables: dict[str, Any] = {"first": PLAIN_DEFAULT_PAGE_SIZE}
    if created_at_gte is not None:
        variables["filter"] = {"updatedAt": {"gte": _datetime_to_plain_iso8601(created_at_gte)}}

    has_next_page = True
    while has_next_page:
        logger.debug(f"Fetching thread IDs for timeline entries with variables: {variables}")
        payload = execute(THREADS_LIST_QUERY, variables)

        data = payload["data"]["threads"]
        for edge in data.get("edges", []):
            yield from _fetch_thread_timeline_entries(execute, edge["node"]["id"], logger, created_at_gte)

        page_info = data["pageInfo"]
        has_next_page = page_info["hasNextPage"]
        if has_next_page:
            variables["after"] = page_info["endCursor"]


def _fetch_thread_timeline_entries(
    execute,
    thread_id: str,
    logger: FilteringBoundLogger,
    created_at_gte: datetime | None = None,
):
    """Fetch timeline entries for a specific thread."""
    variables: dict[str, Any] = {"threadId": thread_id, "first": PLAIN_DEFAULT_PAGE_SIZE}

    has_next_page = True
    while has_next_page:
        payload = execute(TIMELINE_ENTRIES_QUERY, variables)

        thread_data = payload["data"].get("thread")
        if not thread_data:
            break

        timeline_data = thread_data.get("timelineEntries", {})
        edges = timeline_data.get("edges", [])

        entries = []
        for edge in edges:
            entry = _flatten_timeline_entry(edge["node"], thread_id)
            if created_at_gte is not None:
                entry_created_at = _parse_plain_datetime(entry.get("createdAt"))
                # Entries missing a createdAt get included — drop is a stronger claim than we can make here.
                if entry_created_at is not None and entry_created_at < created_at_gte:
                    continue
            entries.append(entry)

        if entries:
            yield entries

        page_info = timeline_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        if has_next_page:
            variables["after"] = page_info["endCursor"]


def plain_source(
    api_key: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    endpoint_config = PLAIN_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown Plain endpoint: {endpoint_name}")

    def get_rows():
        incremental_since: datetime | None = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            incremental_since = _parse_plain_datetime(db_incremental_field_last_value)
            logger.debug(f"Plain: incremental sync for {endpoint_name} since {incremental_since}")

        yield from _make_paginated_request(
            api_key=api_key,
            endpoint_name=endpoint_name,
            logger=logger,
            incremental_since=incremental_since,
        )

    return SourceResponse(
        items=get_rows,
        primary_keys=[endpoint_config.primary_key],
        name=endpoint_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        response = requests.post(
            PLAIN_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": VIEWER_QUERY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            return False, f"Plain API error: {data['errors']}"
        if "data" in data and data["data"].get("myWorkspace"):
            return True, None
        return False, "Could not verify Plain credentials"
    except Exception as e:
        return False, str(e)
