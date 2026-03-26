"""Anonymous opt-out telemetry for hogli CLI.

Events are sent via a direct HTTP POST to PostHog's /capture endpoint.
No SDK is used because the `posthog` package name collides with the repo module.

Opt-out precedence:
    CI=* -> POSTHOG_TELEMETRY_OPT_OUT=1 -> DO_NOT_TRACK=1 -> config enabled: false

Config file: ~/.config/posthog/hogli_telemetry.json
"""

from __future__ import annotations

import os
import sys
import json
import time as _time
import uuid
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

# Write-only project token -- routes events to the correct PostHog project.
# It cannot read data; safe to embed in source code.
_API_KEY = "phc_JYFXrbqdzueOYb0wFUTnCglFKZuC4xRXBW790ewdcvn"
_HOST = "https://us.i.posthog.com"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def get_config_path() -> Path:
    return Path.home() / ".config" / "posthog" / "hogli_telemetry.json"


def _load_config() -> dict[str, Any]:
    try:
        return json.loads(get_config_path().read_text())
    except Exception:
        return {}


def _save_config(config: dict[str, Any]) -> None:
    try:
        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """Return whether telemetry is enabled.

    Checks, in order: POSTHOG_TELEMETRY_OPT_OUT, DO_NOT_TRACK, config file.
    """
    if os.environ.get("CI"):
        return False
    if os.environ.get("POSTHOG_TELEMETRY_OPT_OUT") == "1":
        return False
    if os.environ.get("DO_NOT_TRACK") == "1":
        return False
    config = _load_config()
    return config.get("enabled", True)


def get_anonymous_id() -> str:
    """Return the persistent anonymous UUID, creating one if needed."""
    config = _load_config()
    anon_id = config.get("anonymous_id")
    if anon_id:
        return anon_id
    anon_id = str(uuid.uuid4())
    config["anonymous_id"] = anon_id
    _save_config(config)
    return anon_id


def set_enabled(enabled: bool) -> None:
    """Persist the enabled flag in the config file."""
    config = _load_config()
    config["enabled"] = enabled
    _save_config(config)


def show_first_run_notice_if_needed() -> None:
    """Print a one-time notice to stderr on first invocation, then create config."""
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


def track(event: str, properties: dict[str, Any] | None = None) -> None:
    """Fire a single event to PostHog in a background daemon thread.

    Silently no-ops if telemetry is disabled or on any error.
    """
    if not is_enabled():
        return
    config = _load_config()
    if not config.get("first_run_notice_shown"):
        return

    host = os.environ.get("POSTHOG_TELEMETRY_HOST", _HOST)
    api_key = os.environ.get("POSTHOG_TELEMETRY_API_KEY", _API_KEY)

    props: dict[str, Any] = {
        "$process_person_profile": False,
        "$groups": {"project": "hogli"},
    }
    if properties:
        props.update(properties)

    payload = {
        "api_key": api_key,
        "distinct_id": get_anonymous_id(),
        "event": event,
        "properties": props,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    _debug(f"track: {event} → {host}/capture/", payload)

    thread = threading.Thread(target=_post_event, args=(host, payload), daemon=True)
    thread.start()
    _pending_threads.append(thread)


_pending_threads: deque[threading.Thread] = deque()


def flush(timeout: float = 0.5) -> None:
    """Block until pending telemetry threads complete or *timeout* elapses.

    Tradeoff: higher timeout improves delivery on slow networks (first
    request needs DNS + TLS) but adds latency to CLI exit. 0.5s is
    imperceptible interactively and covers most first-request scenarios.
    """
    deadline = _time.monotonic() + timeout
    while _pending_threads:
        thread = _pending_threads.popleft()
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        thread.join(timeout=remaining)


def _debug(msg: str, payload: dict[str, Any] | None = None) -> None:
    if os.environ.get("HOGLI_DEBUG") != "1":
        return
    sys.stderr.write(f"[telemetry] {msg}\n")
    if payload:
        sys.stderr.write(f"[telemetry] payload: {json.dumps(payload, indent=2)}\n")


def _post_event(host: str, payload: dict[str, Any]) -> None:
    """POST the event payload to the capture endpoint."""
    try:
        import requests
    except ImportError:
        _debug("requests package not installed, skipping telemetry POST")
        return
    try:
        resp = requests.post(
            f"{host}/capture/",
            json=payload,
            timeout=2,
        )
        _debug(f"POST {host}/capture/ -> {resp.status_code}")
    except Exception as exc:
        _debug(f"POST failed: {exc}")
