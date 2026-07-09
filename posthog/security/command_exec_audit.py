"""Process-execution audit logging."""

import os
import re
import uuid
import shlex
import subprocess
import contextvars
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any, Optional

import wrapt
import structlog

# C exec primitive under subprocess.Popen; absent on some platforms (Windows/wasm).
_posixsubprocess: ModuleType | None = None
try:
    import _posixsubprocess as _posixsubprocess_module

    _posixsubprocess = _posixsubprocess_module
except ImportError:  # pragma: no cover
    pass

logger = structlog.get_logger(__name__)

# Reentrancy guard. Emitting a log touches the query-tag context, which on first access
# shells out to `git` (see posthog/git.py via query_tagging.__get_constant_tags) — without
# this guard that subprocess call would recurse straight back into the patched sink.
_in_audit: contextvars.ContextVar[bool] = contextvars.ContextVar("command_exec_audit_in_progress", default=False)

_installed = False

_REDACTED = "[redacted]"
_MAX_ARGS = 64
_MAX_LEN = 4096

# Case-insensitive substrings that mark an argument token or env var name as a secret.
_SECRET_HINTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "credential",
    "private_key",
    "authorization",
)
# Only these env var names keep their value in the log; everything else is counted but redacted.
_ENV_ALLOWLIST = frozenset({"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "HOME", "USER", "SHELL", "PWD"})
_INLINE_ENV_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=(\S+)")
# Long unbroken base64 runs carry encoded payloads — either smuggled file content / secrets
# (which must not leak into logs) or a command an attacker base64'd to evade detection (which
# must still be visible). We can't have it both ways: a blob decodable by an analyst is equally
# decodable by anyone with log access. So we redact the body (no secret leak) but set the
# `has_encoded_blob` flag on the entry, keeping the obfuscation itself an alertable signal.
_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{64,}={0,2}")

# Credentials in URL/DSN userinfo (scheme://user:pass@host) carry no hint word, so name-based
# redaction misses them — common in code that shells out to git/psql/etc. Redact the userinfo.
_URL_USERINFO_RE = re.compile(r"://[^/\s@]+@")
_URL_USERINFO_REPL = f"://{_REDACTED}@"

# Map control chars to spaces so attacker-influenced argv can't forge a second audit line
# under a non-JSON log renderer (e.g. an embedded newline).
_CONTROL_CHARS = dict.fromkeys(range(0x20), " ")
_CONTROL_CHARS[0x7F] = " "

# Characters that let one command string spawn or chain into another.
_SHELL_OPERATORS = frozenset(";|&$`<>\n")

_VOLUME_SUPPRESSION_RULES: dict[str, Callable[[list[str]], bool]] = {
    "uname": lambda tail: all(a.startswith("-") for a in tail),
    "lsb_release": lambda tail: all(a.startswith("-") for a in tail),
    "ldd": lambda tail: tail == ["--version"],
    "file": lambda tail: bool(tail) and tail[0] == "-b",
    "ldconfig": lambda tail: tail == ["-p"],
}

# Context fields pulled from the query-tag ContextVar (set by middleware / Celery / Temporal).
# Identifiers only — deliberately no PII (e.g. user_email) and nothing that can leak secrets
# (http_referer / http_user_agent can carry tokens in query strings). Resolve a user/org from
# the ids out-of-band instead.
_QUERY_TAG_FIELDS = (
    "team_id",
    "user_id",
    "org_id",
    "access_method",
    "is_impersonated",
    "http_request_id",
    "product",
    "kind",
)


def _to_text(value: Any) -> str:
    # Raw bytes/path/str -> str, no sanitization (used for detection scans on the real command).
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "__fspath__"):
        path = os.fspath(value)
        return path.decode("utf-8", "replace") if isinstance(path, bytes) else path
    return str(value)


def _coerce_str(value: Any) -> str:
    # Sanitized for storage: neutralize control chars that could forge a second audit line.
    try:
        return _to_text(value).translate(_CONTROL_CHARS)
    except Exception:
        return _REDACTED


def _is_sensitive(token: str) -> bool:
    # Normalize hyphens to underscores so ``--api-key`` matches the ``api_key`` hint.
    normalized = token.lower().replace("-", "_")
    return any(hint in normalized for hint in _SECRET_HINTS)


def _redact_value(text: str) -> str:
    # Value-based redaction for tokens with no secret hint word: URL/DSN userinfo and long
    # base64 payloads.
    text = _URL_USERINFO_RE.sub(_URL_USERINFO_REPL, text)
    return _BLOB_RE.sub(_REDACTED, text)


def _is_volume_suppressed(command: Any, shell: bool) -> bool:
    if shell or not isinstance(command, (list, tuple)) or not command:
        return False
    argv = [_to_text(token) for token in command]
    predicate = _VOLUME_SUPPRESSION_RULES.get(os.path.basename(argv[0].strip()))
    return predicate is not None and predicate(argv[1:])


def _scrub_args(tokens: Any) -> list[str]:
    result: list[str] = []
    redact_next = False
    full = list(tokens)
    seq = full[:_MAX_ARGS]
    for raw in seq:
        token = _coerce_str(raw)
        if redact_next:
            result.append(_REDACTED)
            redact_next = False
            continue
        if not _is_sensitive(token):
            # Catch creds with no hint word: URL userinfo and base64 payloads (smuggled secrets
            # or obfuscated commands alike).
            result.append(_redact_value(token)[:_MAX_LEN])
            continue
        if "=" in token:
            name = token.split("=", 1)[0]
            result.append(f"{name}={_REDACTED}")
        elif token.startswith("-"):
            # Sensitive flag whose value is the following token, e.g. ``--password secret``.
            # Only flags (``-``) carry a value here — a sensitive *path* gets fully redacted below.
            result.append(token)
            redact_next = True
        else:
            result.append(_REDACTED)
    extra = len(full) - len(seq)
    if extra > 0:
        result.append(f"...(+{extra} args truncated)")
    return result


def _scrub_command_string(command: str) -> str:
    command = command[:_MAX_LEN]
    try:
        # Space-join (not shlex.join) keeps the audit string readable — it's for logs, not re-execution.
        return " ".join(_scrub_args(shlex.split(command)))
    except Exception:
        # Fall back to redacting inline ``KEY=value`` secrets, URL userinfo, and base64 blobs
        # when the line can't be tokenized.
        return _redact_value(
            _INLINE_ENV_RE.sub(
                lambda m: f"{m.group(1)}={_REDACTED}" if _is_sensitive(m.group(1)) else m.group(0),
                command,
            )
        )


def _summarize_env(env: Any) -> tuple[Optional[dict[str, str]], int]:
    if not env or not isinstance(env, Mapping):
        return None, 0
    allowed: dict[str, str] = {}
    redacted = 0
    for key, value in env.items():
        name = _coerce_str(key)
        if name in _ENV_ALLOWLIST and not _is_sensitive(name):
            allowed[name] = _coerce_str(value)[:_MAX_LEN]
        else:
            redacted += 1
    return (allowed or None), redacted


def _context() -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    try:
        from posthog.clickhouse.query_tagging import get_query_tags

        tags = get_query_tags()
        for field in _QUERY_TAG_FIELDS:
            value = getattr(tags, field, None)
            if value is not None:
                ctx[field] = str(value) if isinstance(value, uuid.UUID) else value
    except Exception:
        pass
    try:
        from posthog.models.activity_logging.utils import activity_storage

        ip_address = activity_storage.get_ip_address()
        if ip_address:
            ctx["ip_address"] = ip_address
        client = activity_storage.get_client()
        if client:
            ctx["client"] = client
    except Exception:
        pass
    return ctx


def _emit(
    *,
    component: str,
    sink: str,
    command: Any,
    shell: bool,
    env: Any = None,
    binary: Optional[str] = None,
    cwd: Any = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    if _in_audit.get():
        return
    if _is_volume_suppressed(command, shell):
        return
    token = _in_audit.set(True)
    try:
        payload: dict[str, Any] = {"component": component, "sink": sink, "shell": bool(shell)}
        # raw = the real command (un-redacted) for detection scans; scrubbed = what we store.
        if isinstance(command, (list, tuple)):
            raw = " ".join(_to_text(token) for token in command)
            scrubbed = _scrub_args(command)
            payload["command"] = scrubbed
            payload["binary"] = binary or (scrubbed[0] if scrubbed else None)
        else:
            raw = _to_text(command)
            payload["command"] = _scrub_command_string(raw)
            payload["binary"] = binary

        # Scan the raw command, not the scrubbed copy: an operator inside a redacted token (e.g.
        # `--token=$(cat x)`) would otherwise vanish before this check. Only meaningful under a
        # shell; in argv form (shell=False) these chars are passed literally.
        if shell and any(char in _SHELL_OPERATORS for char in raw):
            payload["has_shell_operators"] = True

        # An encoded payload is worth surfacing whether it's a smuggled secret or an evasion
        # technique — even though we redact the body itself from `command`.
        if _BLOB_RE.search(raw):
            payload["has_encoded_blob"] = True

        if cwd is not None:
            payload["cwd"] = _coerce_str(cwd)

        env_allowed, env_redacted = _summarize_env(env)
        if env_allowed:
            payload["env"] = env_allowed
        if env_redacted:
            payload["env_redacted_count"] = env_redacted
        if extra:
            payload.update(extra)
        payload.update(_context())

        logger.info("command_execution", **payload)
    except Exception:
        try:
            logger.warning("command_execution_audit_failed", sink=sink, exc_info=True)
        except Exception:
            pass
    finally:
        _in_audit.reset(token)


def _arg(args: tuple, kwargs: dict, index: int, name: str, default: Any = None) -> Any:
    if len(args) > index:
        return args[index]
    return kwargs.get(name, default)


def _popen_wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
    # wrapt strips `self`, so the first positional is Popen's `args` (the command).
    try:
        # When `executable` is given it, not args[0], is the program actually run.
        executable = _arg(args, kwargs, 2, "executable")
        _emit(
            component="subprocess",
            sink="subprocess.Popen",
            command=_arg(args, kwargs, 0, "args"),
            shell=_arg(args, kwargs, 8, "shell", False),
            env=_arg(args, kwargs, 10, "env"),
            cwd=_arg(args, kwargs, 9, "cwd"),
            binary=_coerce_str(executable) if executable else None,
        )
    except Exception:
        pass
    return wrapped(*args, **kwargs)


def _fork_exec_wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
    # The C exec primitive beneath subprocess.Popen. Popen calls its own cached reference,
    # so this only fires for code invoking fork_exec directly — i.e. bypassing the Popen hook.
    try:
        argv = args[0] if args else None
        _emit(
            component="subprocess",
            sink="_posixsubprocess.fork_exec",
            command=list(argv) if isinstance(argv, (list, tuple)) else argv,
            shell=False,
        )
    except Exception:
        pass
    return wrapped(*args, **kwargs)


def _system_wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
    try:
        _emit(component="os", sink="os.system", command=_arg(args, kwargs, 0, "command"), shell=True)
    except Exception:
        pass
    return wrapped(*args, **kwargs)


def _spawnvef_wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
    # _spawnvef(mode, file, args, env, func) — the funnel for every os.spawn* alias.
    try:
        file = _arg(args, kwargs, 1, "file")
        # args is argv-style: args[0] is already the program name, so log it as-is and
        # surface the resolved executable via `binary` instead of duplicating it.
        spawn_args = _arg(args, kwargs, 2, "args") or []
        _emit(
            component="os",
            sink="os.spawn",
            command=list(spawn_args),
            shell=False,
            env=_arg(args, kwargs, 3, "env"),
            binary=_coerce_str(file),
        )
    except Exception:
        pass
    return wrapped(*args, **kwargs)


def _make_posix_spawn_wrapper(sink: str) -> Callable[..., Any]:
    def wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
        # posix_spawn(path, argv, env, ...)
        try:
            path = _arg(args, kwargs, 0, "path")
            _emit(
                component="os",
                sink=sink,
                command=list(_arg(args, kwargs, 1, "argv") or []),
                shell=False,
                env=_arg(args, kwargs, 2, "env"),
                binary=_coerce_str(path),
            )
        except Exception:
            pass
        return wrapped(*args, **kwargs)

    return wrapper


def _make_exec_wrapper(sink: str, *, takes_env: bool) -> Callable[..., Any]:
    def wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
        # execv(path, args) / execve(path, args, env) — every os.exec* alias funnels here.
        try:
            path = _arg(args, kwargs, 0, "path")
            _emit(
                component="os",
                sink=sink,
                command=list(_arg(args, kwargs, 1, "args") or []),
                shell=False,
                env=_arg(args, kwargs, 2, "env") if takes_env else None,
                binary=_coerce_str(path),
                extra={"replaces_process": True},
            )
        except Exception:
            pass
        return wrapped(*args, **kwargs)

    return wrapper


def _wrap(module: Any, name: str, wrapper: Any) -> None:
    """Attach a wrapt wrapper, skipping targets that are missing or already wrapped by us.

    Never raises: a sink that can't be wrapped (platform restriction, CPython internal
    change) degrades to "unaudited" with a warning rather than crashing startup.
    """
    try:
        obj = module
        *path, attr = name.split(".")
        for part in path:
            obj = getattr(obj, part, None)
            if obj is None:
                return
        target = getattr(obj, attr, None)
        if target is None or isinstance(target, wrapt.ObjectProxy):
            return
        wrapt.wrap_function_wrapper(module, name, wrapper)
    except Exception:
        logger.warning("command_exec_audit_wrap_failed", target=name, exc_info=True)


def install() -> None:
    """Patch the process-execution sinks. Idempotent; safe to call once per process."""
    global _installed
    if _installed:
        return

    _wrap(subprocess, "Popen.__init__", _popen_wrapper)
    # The C exec primitive under Popen — wrapped to catch direct callers that bypass Popen.
    if _posixsubprocess is not None:
        _wrap(_posixsubprocess, "fork_exec", _fork_exec_wrapper)
    _wrap(os, "system", _system_wrapper)
    # All os.spawn* aliases funnel through this private helper.
    _wrap(os, "_spawnvef", _spawnvef_wrapper)
    _wrap(os, "posix_spawn", _make_posix_spawn_wrapper("os.posix_spawn"))
    _wrap(os, "posix_spawnp", _make_posix_spawn_wrapper("os.posix_spawnp"))
    _wrap(os, "execv", _make_exec_wrapper("os.execv", takes_env=False))
    _wrap(os, "execve", _make_exec_wrapper("os.execve", takes_env=True))

    # Set only after every sink has been attempted, so a mid-install failure doesn't
    # permanently mark the audit "done" with sinks left unwrapped.
    _installed = True
