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

## Process observability (for agents/debugging)

No setup flag needed — observability is always on when `./bin/start` is running.

Each process writes one file:

- `/tmp/posthog-<process>.json` — structured status (pid, status, ready flag, exit code, timestamps, CPU/mem metrics)

The `status` field transitions `starting` → `running` → `stopped` or `crashed`.
A separate `ready` boolean flips to `true` once `ready_pattern` matches.

Log output lives in phrocs' in-memory scrollback buffer (10,000 lines per process)
and is served over a Unix domain socket at `/tmp/phrocs.sock`.

### MCP tools (preferred for agents)

The project ships a local MCP server (`bin/phrocs-mcp-server.py`) registered in `.mcp.json`.
When Claude Code loads the project, two tools are available automatically:

- **`get_process_status`** — returns status JSON for one or all processes;
  pass no argument for a dashboard of all running processes
- **`get_process_logs`** — returns recent log lines for a named process;
  accepts `lines` (default 100, max 500) and `grep` (regex filter) arguments

### Direct status access (fallback)

If the MCP server is not configured, read the status file directly:

```bash
cat /tmp/posthog-backend.json   # status snapshot
```

## Key references

- `common/hogli/manifest.yaml` — command definitions (source of truth)
- `common/hogli/commands.py` — extension point for custom Click commands
- `common/hogli/README.md` — full developer and architecture docs
