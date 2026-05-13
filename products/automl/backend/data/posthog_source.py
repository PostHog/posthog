"""Run HogQL queries against PostHog's public API on behalf of a customer.

Same pattern the MCP server uses: HTTP POST to ``/api/projects/{project_id}/query/``
with the customer's personal API key. Works against us-cloud, eu-cloud, and
self-hosted PostHog instances — no Django bootstrap required.

Personal API keys: create one at ``<host>/me/settings#personal-api-keys``
with the ``query:read`` scope (or broader). Export as
``POSTHOG_PERSONAL_API_KEY``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import polars as pl
import requests
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_HOST = "https://us.posthog.com"
DEFAULT_TIMEOUT_S = 120
API_KEY_ENV_VAR = "POSTHOG_PERSONAL_API_KEY"


class HogQLResultTruncatedError(RuntimeError):
    """Raised when the HogQL response was truncated by the server's row cap.

    PostHog's query API caps responses at a small default (~100 rows) when no
    LIMIT is specified in the SQL. Training on truncated data is silently
    meaningless, so we fail-fast unless the caller explicitly opts in.
    """


@dataclass(frozen=True)
class PostHogClient:
    api_key: str
    project_id: int
    host: str = DEFAULT_HOST
    timeout_s: int = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(
        cls,
        *,
        project_id: int,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> PostHogClient:
        resolved_key = api_key or os.environ.get(API_KEY_ENV_VAR)
        if not resolved_key:
            raise RuntimeError(
                f"No PostHog personal API key provided. Pass --api-key or set {API_KEY_ENV_VAR}. "
                "Create one at <host>/me/settings#personal-api-keys with the query:read scope."
            )
        return cls(api_key=resolved_key, project_id=project_id, host=host or DEFAULT_HOST, timeout_s=timeout_s)

    def run_hogql(self, query: str, *, allow_truncated: bool = False) -> pl.DataFrame:
        url = f"{self.host.rstrip('/')}/api/projects/{self.project_id}/query/"
        payload: dict[str, Any] = {"query": {"kind": "HogQLQuery", "query": query}}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        logger.info(
            "hogql_request_start",
            host=self.host,
            project_id=self.project_id,
            query_chars=len(query),
        )
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout_s)
        if resp.status_code >= 400:
            logger.error(
                "hogql_request_failed",
                status=resp.status_code,
                body=resp.text[:1000],
            )
            resp.raise_for_status()
        data = resp.json()
        columns: list[str] = list(data.get("columns") or [])
        rows: list[Any] = list(data.get("results") or [])
        has_more = bool(data.get("hasMore"))
        logger.info(
            "hogql_request_done",
            rows=len(rows),
            cols=len(columns),
            has_more=has_more,
        )
        if has_more and not allow_truncated:
            raise HogQLResultTruncatedError(
                f"HogQL response was truncated to {len(rows)} rows (server set hasMore=true). "
                "Training on truncated data is silently meaningless. Add a LIMIT to the SQL "
                "(e.g. LIMIT 1000000) or pass --allow-truncated to override."
            )
        if has_more:
            logger.warning("hogql_result_truncated_accepted", rows=len(rows))
        if not rows:
            return pl.DataFrame({col: [] for col in columns})
        return pl.DataFrame(rows, schema=columns, orient="row")
