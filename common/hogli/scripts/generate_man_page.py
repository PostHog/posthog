#!/usr/bin/env python3
"""Generate the hogli(1) man page from live CLI help output."""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

import click

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMON_DIR = REPO_ROOT / "common"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from hogli.core.cli import cli  # noqa: E402

ANSI_RE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")
TERMINAL_WIDTH = 120


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate hogli(1) from the current CLI.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the generated man page to this path. If omitted, print to stdout.",
    )
    return parser.parse_args()


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _escape_roff(line: str) -> str:
    escaped = line.replace("\\", r"\\")
    if escaped.startswith(".") or escaped.startswith("'"):
        escaped = rf"\&{escaped}"
    return escaped


def _collect_help_text() -> str:
    ctx = click.Context(cli, info_name="hogli", terminal_width=TERMINAL_WIDTH, color=False)
    return _strip_ansi(cli.get_help(ctx)).strip()


def _collect_command_help() -> list[tuple[str, str]]:
    root_ctx = click.Context(cli, info_name="hogli", terminal_width=TERMINAL_WIDTH, color=False)
    command_help_sections: list[tuple[str, str]] = []
    for command_name, command in sorted(cli.commands.items()):
        config = getattr(command, "hogli_config", {})
        if config.get("hidden", False):
            continue

        sub_ctx = click.Context(
            command,
            info_name=f"hogli {command_name}",
            parent=root_ctx,
            terminal_width=TERMINAL_WIDTH,
            color=False,
        )
        command_help_sections.append((command_name, _strip_ansi(command.get_help(sub_ctx)).strip()))

    return command_help_sections


def _render(help_text: str, command_help_sections: list[tuple[str, str]]) -> str:
    escaped_help_lines = [_escape_roff(line) for line in help_text.splitlines()]
    lines = [
        '.TH HOGLI 1 "Auto-generated" "PostHog" "User Commands"',
        ".SH NAME",
        "hogli \\- PostHog developer CLI",
        ".SH SYNOPSIS",
        ".B hogli",
        "[\\fIOPTIONS\\fR] \\fICOMMAND\\fR [\\fIARGS\\fR]...",
        ".SH DESCRIPTION",
        "\\fBhogli\\fR is the unified command line interface for PostHog development workflows.",
        "This page is generated from the current CLI help output.",
        ".SH HELP OUTPUT",
        ".nf",
        *escaped_help_lines,
        ".fi",
    ]

    if command_help_sections:
        lines.append(".SH COMMAND HELP OUTPUT")
        for command_name, command_help in command_help_sections:
            lines.extend(
                [
                    ".SS \\fB" + _escape_roff(command_name) + "\\fR",
                    ".nf",
                    *[_escape_roff(line) for line in command_help.splitlines()],
                    ".fi",
                ]
            )

    lines.extend(
        [
            ".SH FILES",
            ".TP",
            "\\fIcommon/hogli/manifest.yaml\\fR",
            "Command definitions and metadata.",
            ".TP",
            "\\fIcommon/hogli/core/cli.py\\fR",
            "CLI group and command registration.",
            ".TP",
            "\\fIcommon/hogli/commands.py\\fR",
            "Custom Click commands.",
            "",
        ]
    )
    return "\n".join(lines)


def _write(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def main() -> int:
    args = _parse_args()
    content = _render(_collect_help_text(), _collect_command_help())

    if not args.output:
        sys.stdout.write(content)
        return 0

    _write(args.output, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
