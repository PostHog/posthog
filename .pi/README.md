# `.pi/` — pi coding agent config

Project-local config for the [pi coding agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent).
Anything here is auto-loaded when a PostHog dev runs `pi` from the repo root.

## What's here

- `extensions/phrocs.ts` — bridges the local [phrocs](../tools/phrocs/) MCP server
  into pi. Spawns `uv run python tools/phrocs/mcp_server.py` on session start,
  registers each phrocs tool (`get_process_status`, `get_process_logs`,
  `send_keys`, `toggle_process`) as a first-class pi tool.

  Speaks the MCP stdio JSON-RPC 2.0 wire protocol directly — no npm deps, no
  `node_modules`, nothing to install. Clone the repo, run `pi`, phrocs tools
  appear.

- `extensions/tsconfig.json` + `extensions/ambient.d.ts` — keep the editor
  quiet. Extensions run via jiti at runtime; these files only exist so
  tsserver doesn't red-flag the imports.

## Commands

Inside pi: `/phrocs-status`, `/phrocs-reload`.

## Adding another internal MCP server

If you add a new stdio MCP server that's useful to PostHog devs, drop a sibling
file next to `phrocs.ts` using the same pattern. Keep it zero-deps so the
repo stays install-free on the pi side.
