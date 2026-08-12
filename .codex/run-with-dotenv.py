from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import NoReturn

from dotenv import dotenv_values

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BLOCKED_NAMES = frozenset(
    {
        "BASH_ENV",
        "BASHOPTS",
        "CDPATH",
        "CLASSPATH",
        "COMPOSE_FILE",
        "COMPOSE_PATH_SEPARATOR",
        "COMPOSE_PROFILES",
        "COMPOSE_PROJECT_NAME",
        "CODEX_PROTECTED_ENV_NAMES",
        "CODEX_SANDBOX",
        "CODEX_SANDBOX_NETWORK_DISABLED",
        "DOCKER_CONFIG",
        "DOCKER_HOST",
        "ENV",
        "GIT_EXEC_PATH",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_TEMPLATE_DIR",
        "GLOBIGNORE",
        "IFS",
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "LESSCLOSE",
        "LESSOPEN",
        "NODE_OPTIONS",
        "NODE_PATH",
        "PERL5LIB",
        "PERL5OPT",
        "PROMPT_COMMAND",
        "POSTHOG_DEV_SANDBOX",
        "POSTHOG_DEV_SANDBOX_REQUIRED",
        "POSTHOG_SKIP_DOTENV",
        "PS4",
        "PYTHONBREAKPOINT",
        "PYTHONCASEOK",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONWARNINGS",
        "RUBYLIB",
        "RUBYOPT",
        "SHELLOPTS",
        "SSH_AUTH_SOCK",
        "ZDOTDIR",
        "_JAVA_OPTIONS",
    }
)
_BLOCKED_PREFIXES = (
    "BASH_FUNC_",
    "CARGO_TARGET_",
    "DYLD_",
    "GIT_CONFIG_",
    "LD_",
)


def _is_blocked(name: str, protected_names: set[str]) -> bool:
    return name in protected_names or name in _BLOCKED_NAMES or name.startswith(_BLOCKED_PREFIXES)


def main() -> NoReturn:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        raise SystemExit("usage: run-with-dotenv.py <env-file> -- <command> [args...]")

    protected_names = {name for name in os.environ.pop("CODEX_PROTECTED_ENV_NAMES", "").split(":") if name}
    values = dotenv_values(Path(sys.argv[1]), interpolate=False)
    invalid_names = sorted(name for name in values if not _ENVIRONMENT_NAME.fullmatch(name))
    blocked_names = sorted(
        name
        for name, value in values.items()
        if _is_blocked(name, protected_names) and (name not in os.environ or os.environ[name] != value)
    )

    if invalid_names:
        raise SystemExit(f"error: .env contains invalid variable names: {', '.join(invalid_names)}")
    if blocked_names:
        raise SystemExit(f"error: .env cannot override protected variables: {', '.join(blocked_names)}")

    environment = os.environ.copy()
    environment.update({name: value for name, value in values.items() if value is not None})
    # argv is the caller's own command line, which with-flox execs directly when no .env is present.
    # The .env is the untrusted input, and the blocked-name checks above keep it out of the exec.
    # nosemgrep: python.lang.security.audit.dangerous-os-exec-tainted-env-args.dangerous-os-exec-tainted-env-args
    os.execvpe(sys.argv[3], sys.argv[3:], environment)


if __name__ == "__main__":
    main()
