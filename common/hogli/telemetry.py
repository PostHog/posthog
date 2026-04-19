"""Anonymous opt-out telemetry for hogli CLI.

Events are queued in-process and flushed as a single batch POST to
PostHog's ``/batch/`` endpoint.

Opt-out precedence:
    CI=* -> POSTHOG_TELEMETRY_OPT_OUT=1 -> DO_NOT_TRACK=1 -> config enabled: false

Config file: ~/.config/posthog/hogli_telemetry.json
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import atexit
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import click
import requests

# Write-only project token -- routes events to the correct PostHog project.
# It cannot read data; safe to embed in source code.
_DEFAULT_API_KEY = "phc_JYFXrbqdzueOYb0wFUTnCglFKZuC4xRXBW790ewdcvn"
_DEFAULT_HOST = "https://us.i.posthog.com"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TelemetryConfig(TypedDict, total=False):
    enabled: bool
    anonymous_id: str
    first_run_notice_shown: bool
    is_posthog_org_member: bool
    org_check_timestamp: float


def get_config_path() -> Path:
    return Path.home() / ".config" / "posthog" / "hogli_telemetry.json"


def _load_config() -> TelemetryConfig:
    try:
        return json.loads(get_config_path().read_text())
    except Exception:
        return TelemetryConfig()


def _save_config(config: TelemetryConfig) -> None:
    try:
        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TelemetryClient
# ---------------------------------------------------------------------------


class TelemetryClient:
    """Queue-based telemetry client that batches events into a single POST."""

    def __init__(self) -> None:
        self._queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # -- config-backed helpers --

    @property
    def _host(self) -> str:
        return os.environ.get("POSTHOG_TELEMETRY_HOST", _DEFAULT_HOST)

    @property
    def _api_key(self) -> str:
        return os.environ.get("POSTHOG_TELEMETRY_API_KEY", _DEFAULT_API_KEY)

    def is_enabled(self) -> bool:
        if os.environ.get("CI"):
            return False
        if os.environ.get("POSTHOG_TELEMETRY_OPT_OUT") == "1":
            return False
        if os.environ.get("DO_NOT_TRACK") == "1":
            return False
        return _load_config().get("enabled", True)

    def get_anonymous_id(self) -> str:
        config = _load_config()
        anon_id = config.get("anonymous_id")
        if anon_id:
            return anon_id
        anon_id = str(uuid.uuid4())
        config["anonymous_id"] = anon_id
        _save_config(config)
        return anon_id

    def set_enabled(self, enabled: bool) -> None:
        config = _load_config()
        config["enabled"] = enabled
        _save_config(config)

    def show_first_run_notice_if_needed(self) -> None:
        config = _load_config()
        if config.get("first_run_notice_shown"):
            return

        click.echo(
            "\n"
            "hogli collects anonymous usage data to help improve the developer experience.\n"
            "No personal information is collected -- only command names and timing.\n"
            "\n"
            "You can opt out at any time:\n"
            "  hogli telemetry:off          (persistent)\n"
            "  POSTHOG_TELEMETRY_OPT_OUT=1  (per-session / CI)\n"
            "  DO_NOT_TRACK=1               (cross-tool convention)\n"
            "\n"
            "Run `hogli telemetry:status` for details.\n",
            err=True,
        )

        config["first_run_notice_shown"] = True
        if "anonymous_id" not in config:
            config["anonymous_id"] = str(uuid.uuid4())
        config.setdefault("enabled", True)
        _save_config(config)

    # -- event tracking --

    def track(self, event: str, properties: dict[str, Any] | None = None) -> None:
        """Queue a single event. No-ops if telemetry is disabled."""
        if not self.is_enabled():
            return
        config = _load_config()
        if not config.get("first_run_notice_shown"):
            return

        props: dict[str, Any] = {
            "$process_person_profile": False,
            "$groups": {"project": "hogli"},
        }
        if properties:
            props.update(properties)

        entry = {
            "event": event,
            "distinct_id": self.get_anonymous_id(),
            "properties": props,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        _debug(f"queued: {event}")
        with self._lock:
            self._queue.append(entry)

    def flush(self, timeout: float = 2.0) -> None:
        """Send queued events as a single batch POST, blocking up to *timeout*."""
        with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()

        thread = threading.Thread(target=self._send_batch, args=(batch,), daemon=True)
        thread.start()
        thread.join(timeout=timeout)

    def _send_batch(self, batch: list[dict[str, Any]]) -> None:
        host = self._host
        api_key = self._api_key
        url = f"{host}/batch/"

        body = {"api_key": api_key, "batch": batch}
        _debug(f"POST {url} ({len(batch)} events)", body)

        try:
            resp = requests.post(url, json=body, timeout=5)
            _debug(f"POST {url} -> {resp.status_code}")
        except Exception as exc:
            _debug(f"POST failed: {exc}")


# ---------------------------------------------------------------------------
# Module-level singleton and public API
# ---------------------------------------------------------------------------

_client = TelemetryClient()
atexit.register(_client.flush)


def is_enabled() -> bool:
    return _client.is_enabled()


def get_anonymous_id() -> str:
    return _client.get_anonymous_id()


def set_enabled(enabled: bool) -> None:
    _client.set_enabled(enabled)


def show_first_run_notice_if_needed() -> None:
    _client.show_first_run_notice_if_needed()


def track(event: str, properties: dict[str, Any] | None = None) -> None:
    _client.track(event, properties)


def flush(timeout: float = 2.0) -> None:
    _client.flush(timeout)


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------


def _debug(msg: str, payload: dict[str, Any] | None = None) -> None:
    if os.environ.get("HOGLI_DEBUG") != "1":
        return
    sys.stderr.write(f"[telemetry] {msg}\n")
    if payload:
        sys.stderr.write(f"[telemetry] payload: {json.dumps(payload, indent=2)}\n")
