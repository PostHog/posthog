"""Pure data layer for sandbox.env: parse the user's KEY=value secrets file
(with `# comment` descriptions) and render the agent-facing context block that
bin/sandbox appends to the sandbox CLAUDE.md. No docker calls, no secret values
in the output — parse_env_comments never even reads the values, so they cannot
leak into CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path

from sandbox_addons import REGISTRY_DIR

ENV_FILE = REGISTRY_DIR / "sandbox.env"

TEMPLATE = """\
# Secrets for your PostHog dev sandboxes, injected as environment variables.
#
# One KEY=value per line. The `# comment` lines directly above a KEY become the
# description the in-sandbox agent sees in its CLAUDE.md. The values are set in
# the sandbox environment but never shown to the agent: it uses them by
# reference (e.g. $SLACK_TOKEN), so they stay out of the transcript. Put a blank
# line between entries. Applies on the next `sandbox create` / `sandbox start`.
#
# Example (uncomment and fill in):
#
# # Slack token. Use by reference, e.g.:
# # curl -H "Authorization: Bearer $SLACK_TOKEN" https://slack.com/api/auth.test
# SLACK_TOKEN=xoxb-...
"""


def ensure_file(path: Path = ENV_FILE) -> Path:
    """Create the secrets file with the commented template if absent (mode 0600)."""
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE)
        path.chmod(0o600)
    return path


def append_var(name: str, value: str, comment: str = "", path: Path = ENV_FILE) -> None:
    """Append a `# comment` + KEY=value block to the secrets file (mode 0600).

    Creates the file from the template first if needed. Callers append only vars
    that aren't already set, so this does not de-duplicate.
    """
    ensure_file(path)
    lines = ["", *(f"# {c}" for c in comment.splitlines()), f"{name}={value}"]
    with path.open("a") as f:
        f.write("\n".join(lines) + "\n")
    path.chmod(0o600)


def parse_env_comments(path: Path = ENV_FILE) -> list[tuple[str, str]]:
    """Return (name, comment) for each KEY=value in a .env-style file.

    `# comment` lines directly above an assignment attach to it; a blank line
    resets the pending comment. Values are deliberately not returned: only the
    entrypoint reads the file for values, and they must never reach CLAUDE.md.
    """
    if not path.is_file():
        return []
    pairs: list[tuple[str, str]] = []
    pending: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            pending = []
            continue
        if line.startswith("#"):
            pending.append(line.lstrip("#").strip())
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            pending = []
            continue
        name = line.partition("=")[0].strip()
        if name:
            pairs.append((name, "\n".join(pending)))
        pending = []
    return pairs


def render_context_markdown(env_vars: list[tuple[str, str]], tools: list[tuple[str, str]]) -> str:
    """Render provisioned env vars + tools into the CLAUDE.md context block.

    Lists env var names with their comments, never the values.
    """
    if not env_vars and not tools:
        return ""

    lines = [
        "## Sandbox environment",
        "",
        "You are running in an isolated PostHog dev sandbox. The items below are provisioned for you.",
    ]

    if env_vars:
        lines += [
            "",
            "### Secrets (environment variables)",
            "",
            "These are already set in your shell environment. Use them by reference "
            "(for example `$SLACK_TOKEN`); do not print, echo, or `cat` their values, "
            "and avoid `curl -v`, so the secrets stay out of the transcript.",
            "",
        ]
        for name, comment in env_vars:
            comment_lines = comment.splitlines()
            head = comment_lines[0] if comment_lines else ""
            lines.append(f"- `{name}`: {head}" if head else f"- `{name}`")
            lines += [f"  {extra}" for extra in comment_lines[1:]]

    if tools:
        lines += ["", "### Installed CLI tools", ""]
        for name, desc in tools:
            desc = (desc or "").strip()
            lines.append(f"- `{name}`: {desc}" if desc else f"- `{name}`")

    return "\n".join(lines) + "\n"
