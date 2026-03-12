---
name: hogli
description: >
  PostHog developer CLI and repo tooling reference. Use when the user mentions
  hogli, asks about repo CLI tools, bin scripts, Makefiles, how to run/build/test/lint,
  or any dev environment commands.
---

# hogli - PostHog Developer CLI

Unified CLI for PostHog development. Wraps all repo scripts, bin commands, and tooling behind a single entry point. There is no Makefile — hogli is the equivalent.

Run `hogli --help` to get the full, current command list. Run `hogli <command> --help` for any subcommand.

## MCP tools (for agents)

phrocs exposes a built-in MCP HTTP server on `http://127.0.0.1:5835/mcp` while the TUI is
running. This is registered in `.mcp.json`, so two tools are available automatically whenever
agents are used in this repo:

- **`get_process_status`** — returns status, PID, and line count for one or all processes;
  pass no argument for a dashboard of all running processes
- **`get_process_logs`** — returns recent log lines for a named process;
  accepts `lines` (default 100, max 500) and `grep` (regex filter) arguments

The server reads live in-memory data from phrocs directly — no `--log` mode or file setup
required. The default port can be changed with the `--mcp-addr` flag: `phrocs --mcp-addr 0.0.0.0:5836 …`.

## Process logging (for debugging)

`hogli dev:setup --log` enables file logging for all phrocs processes (separate from MCP).
Each process writes two files:

- `/tmp/posthog-<process>.log` — full stdout/stderr stream
- `/tmp/posthog-<process>.json` — structured status (pid, status, ready flag, exit code, timestamps)

## Key references

- `common/hogli/manifest.yaml` — command definitions (source of truth)
- `common/hogli/commands.py` — extension point for custom Click commands
- `common/hogli/README.md` — full developer and architecture docs
