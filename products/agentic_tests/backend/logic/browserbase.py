"""
Browserbase session lifecycle.

Wraps the small bits of Browserbase's REST API we need: create a session,
get its CDP connect URL, get the human-facing replay URL. We deliberately
avoid the official SDK to keep the runtime footprint minimal.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)

BROWSERBASE_API = "https://api.browserbase.com/v1"

# Regions Browserbase supports. Keep in sync with their docs:
# https://docs.browserbase.com/features/browser-regions
SUPPORTED_REGIONS = ("us-west-2", "us-east-1", "eu-central-1", "ap-southeast-1")
DEFAULT_REGION = "us-west-2"


@dataclass(frozen=True)
class BrowserbaseSession:
    id: str
    connect_url: str  # ws:// or wss:// for Playwright `connect_over_cdp`
    replay_url: str  # https URL a human can open to watch playback
    region: str  # which region this session ran in


def _api_key() -> str:
    key = getattr(settings, "BROWSERBASE_API_KEY", None)
    if not key:
        raise RuntimeError("BROWSERBASE_API_KEY is not configured")
    return key


def _project_id() -> str:
    pid = getattr(settings, "BROWSERBASE_PROJECT_ID", None)
    if not pid:
        raise RuntimeError("BROWSERBASE_PROJECT_ID is not configured")
    return pid


@contextmanager
def open_session(*, region: str | None = None, keep_alive: bool = False) -> Iterator[BrowserbaseSession]:
    """Create a Browserbase session, yield it, and request termination on exit."""
    headers = {"X-BB-API-Key": _api_key(), "Content-Type": "application/json"}
    effective_region = region if region in SUPPORTED_REGIONS else DEFAULT_REGION
    payload: dict[str, object] = {
        "projectId": _project_id(),
        "keepAlive": keep_alive,
        "region": effective_region,
    }

    resp = requests.post(f"{BROWSERBASE_API}/sessions", json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    session = BrowserbaseSession(
        id=data["id"],
        connect_url=data["connectUrl"],
        # Browserbase replay URL convention — confirm with their docs if their dashboard
        # path changes. As of now: https://www.browserbase.com/sessions/{id}
        replay_url=f"https://www.browserbase.com/sessions/{data['id']}",
        region=effective_region,
    )

    try:
        yield session
    finally:
        try:
            requests.post(
                f"{BROWSERBASE_API}/sessions/{session.id}",
                json={"status": "REQUEST_RELEASE", "projectId": _project_id()},
                headers=headers,
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.warning("browserbase_release_failed", session_id=session.id, error=str(exc))
