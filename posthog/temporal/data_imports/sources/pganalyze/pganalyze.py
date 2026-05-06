from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.pganalyze.queries import ISSUES_QUERY, SERVERS_QUERY
from posthog.temporal.data_imports.sources.pganalyze.settings import (
    PGANALYZE_API_URL,
    PGANALYZE_ENDPOINTS,
    PGANALYZE_MAX_RETRY_ATTEMPTS,
    PGANALYZE_REQUEST_TIMEOUT_SECONDS,
)


class PgAnalyzeRetryableError(Exception):
    pass


def _build_session(api_key: str):
    return make_tracked_session(
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
    )


def _post_graphql(
    session: Any,
    api_url: str,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    @retry(
        retry=retry_if_exception_type(PgAnalyzeRetryableError),
        stop=stop_after_attempt(PGANALYZE_MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=30),
        reraise=True,
    )
    def _execute() -> dict[str, Any]:
        response = session.post(
            api_url,
            json={"query": query, "variables": variables},
            timeout=PGANALYZE_REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code >= 500:
            raise PgAnalyzeRetryableError(f"pganalyze: server error {response.status_code}")
        if response.status_code == 429:
            raise PgAnalyzeRetryableError("pganalyze: rate limited (429)")

        try:
            payload = response.json()
        except Exception:
            if not response.ok:
                raise Exception(
                    f"{response.status_code} Client Error: {response.reason} (pganalyze API: {response.text})"
                )
            raise Exception(f"Unexpected pganalyze response: {response.text}")

        if "errors" in payload:
            error_messages = "; ".join(e.get("message", "") for e in payload["errors"])
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (pganalyze: {error_messages})")
            raise Exception(f"pganalyze GraphQL error: {error_messages}")

        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} (pganalyze: {payload})")

        if "data" not in payload:
            raise Exception(f"Unexpected pganalyze response format. Keys: {list(payload.keys())}")

        return payload["data"]

    return _execute()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fetch_servers(session: Any, api_url: str, organization_slug: str) -> list[dict[str, Any]]:
    data = _post_graphql(session, api_url, SERVERS_QUERY, {"organizationSlug": organization_slug})
    return data.get("getServers") or []


def _iter_servers(session: Any, api_url: str, organization_slug: str) -> Iterator[dict[str, Any]]:
    synced_at = _utc_now_iso()
    for server in _fetch_servers(session, api_url, organization_slug):
        yield {**server, "synced_at": synced_at}


def _iter_issues(
    session: Any,
    api_url: str,
    servers: list[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    logger.debug(f"pganalyze: fetched {len(servers)} servers for issues fan-out")

    for server in servers:
        server_human_id = server.get("humanId")
        if not server_human_id:
            continue

        synced_at = _utc_now_iso()
        issues_payload = _post_graphql(session, api_url, ISSUES_QUERY, {"serverId": server_human_id})
        for issue in issues_payload.get("getIssues") or []:
            yield {
                **issue,
                "serverHumanId": server_human_id,
                "serverName": server.get("name"),
                "synced_at": synced_at,
            }


def pganalyze_source(
    api_key: str,
    api_url: str | None,
    organization_slug: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    endpoint_config = PGANALYZE_ENDPOINTS.get(endpoint_name)
    if endpoint_config is None:
        raise ValueError(f"Unknown pganalyze endpoint: {endpoint_name}")

    resolved_api_url = api_url or PGANALYZE_API_URL

    def get_rows() -> Iterator[dict[str, Any]]:
        session = _build_session(api_key)
        try:
            if endpoint_name == "servers":
                yield from _iter_servers(session, resolved_api_url, organization_slug)
                return

            if endpoint_name == "issues":
                servers = _fetch_servers(session, resolved_api_url, organization_slug)
                yield from _iter_issues(session, resolved_api_url, servers, logger)
                return

            raise ValueError(f"Unhandled pganalyze endpoint: {endpoint_name}")
        finally:
            session.close()

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


def validate_credentials(api_key: str, organization_slug: str, api_url: str | None) -> tuple[bool, str | None]:
    try:
        session = _build_session(api_key)
        try:
            response = session.post(
                api_url or PGANALYZE_API_URL,
                json={
                    "query": SERVERS_QUERY,
                    "variables": {"organizationSlug": organization_slug},
                },
                timeout=10,
            )
        finally:
            session.close()

        if response.status_code in (401, 403):
            return False, "Invalid pganalyze API token. Please check your API key and organization slug."

        try:
            payload = response.json()
        except Exception:
            return False, f"Unexpected pganalyze response: {response.text[:200]}"

        if "errors" in payload:
            messages = "; ".join(e.get("message", "") for e in payload["errors"])
            return False, f"pganalyze API error: {messages}"

        if "data" in payload and "getServers" in payload["data"]:
            return True, None

        return False, "Could not verify pganalyze credentials"
    except Exception as e:
        return False, str(e)
