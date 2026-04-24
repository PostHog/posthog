"""Audit logging for `manage.py` invocations.

Wraps Django's ``execute_from_command_line`` so that every command run via
``manage.py`` in a cloud environment emits one PostHog event capturing the
command name, a secret-redacted view of the arguments, exit code, duration,
and host/user context. Commands invoked via ``call_command()`` from tests,
Celery, migrations, or web code are intentionally not captured.
"""

import os
import time
import socket
import getpass
import logging
from collections.abc import Callable, Iterable
from typing import Optional

logger = logging.getLogger(__name__)

# Commands where full argv is operationally useful and known not to accept
# secrets as flag values. Everything else has its argv redacted.
SAFE_FULL_ARGV_COMMANDS: frozenset[str] = frozenset(
    {
        "migrate",
        "makemigrations",
        "showmigrations",
        "sqlmigrate",
        "collectstatic",
        "check",
        "diffsettings",
        "showpluginconfigs",
        "run_async_migrations",
    }
)

# No-op / meta invocations that are too noisy to audit.
SKIP_COMMANDS: frozenset[str] = frozenset({"", "help", "--help", "-h", "--version", "version"})

EVENT_NAME = "$management_command_run"


def _redact_argv(argv: list[str]) -> tuple[list[str], bool]:
    """Return ``(redacted_args, was_redacted)``.

    ``argv[0]`` is ``manage.py``, ``argv[1]`` is the command, ``argv[2:]`` are
    the command's own args. For allowlisted commands the raw args are returned
    unchanged. Otherwise long flag values are dropped (``--foo=bar`` → ``--foo``,
    ``--foo`` is kept as-is with its following value dropped), short flags are
    kept, and positionals are collapsed to ``<N positional>``.
    """
    command = argv[1] if len(argv) > 1 else ""
    rest = argv[2:]

    if command in SAFE_FULL_ARGV_COMMANDS:
        return list(rest), False

    redacted: list[str] = []
    positional_count = 0
    skip_next_value = False

    for token in rest:
        if skip_next_value:
            skip_next_value = False
            continue
        if token.startswith("--"):
            if "=" in token:
                name = token.split("=", 1)[0]
                redacted.append(f"{name}=<redacted>")
            else:
                # Value (if any) is the next token; we drop it because we can't
                # tell if it's a secret. Boolean flags just get recorded as-is.
                redacted.append(token)
                skip_next_value = True
        elif token.startswith("-") and len(token) > 1:
            # Short flags: keep the flag but not its value.
            redacted.append(token)
            skip_next_value = True
        else:
            positional_count += 1

    if positional_count:
        redacted.append(f"<{positional_count} positional>")

    return redacted, True


def run_with_audit(execute_fn: Callable[[Iterable[str]], None], argv: list[str]) -> None:
    """Run ``execute_fn(argv)`` and emit one audit event on completion.

    Preserves the original exit code and any raised exception. Audit emission
    is wrapped in a blanket try/except — a broken telemetry pipeline must never
    break a real command.
    """
    command = argv[1] if len(argv) > 1 else ""
    start = time.monotonic()
    exit_code = 0
    error_type: Optional[str] = None
    try:
        execute_fn(argv)
    except SystemExit as e:
        if e.code is None:
            exit_code = 0
        elif isinstance(e.code, int):
            exit_code = e.code
        else:
            exit_code = 1
        raise
    except BaseException as e:
        exit_code = 1
        error_type = type(e).__name__
        raise
    finally:
        try:
            _emit(command, argv, start, exit_code, error_type)
        except Exception:
            logger.exception("management command audit emission failed")


def _emit(
    command: str,
    argv: list[str],
    start: float,
    exit_code: int,
    error_type: Optional[str],
) -> None:
    if command in SKIP_COMMANDS:
        return

    from posthog.cloud_utils import is_cloud

    if not is_cloud():
        return

    from django.conf import settings

    from posthog.ph_client import ph_scoped_capture
    from posthog.utils import get_machine_id

    argv_redacted, was_redacted = _redact_argv(argv)

    properties = {
        "command": command,
        "argv_redacted": argv_redacted,
        "argv_was_redacted": was_redacted,
        "argv_length": max(0, len(argv) - 2),
        "exit_code": exit_code,
        "error_type": error_type,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "hostname": socket.gethostname(),
        "pod_name": os.environ.get("HOSTNAME") or os.environ.get("POD_NAME"),
        "username": _safe_username(),
        "deployment": os.environ.get("DEPLOYMENT"),
        "commit_sha": os.environ.get("POSTHOG_COMMIT_SHA") or os.environ.get("SENTRY_RELEASE"),
    }

    with ph_scoped_capture() as capture:
        capture(
            distinct_id=get_machine_id(),
            event=EVENT_NAME,
            properties=properties,
            groups={"instance": settings.SITE_URL},
        )


def _safe_username() -> Optional[str]:
    try:
        return getpass.getuser()
    except Exception:
        return None
