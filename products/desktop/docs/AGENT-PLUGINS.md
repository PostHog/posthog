# Agent Plugins

PostHog Desktop supports skills, Streamable HTTP MCP servers, and stdio MCP servers from local [Agent Plugins 1.0.0](https://agent-plugins.org/).

## Add a local plugin

1. Open **Skills**.
2. Select the **Plugins** tab.
3. Select **Add local plugin**.
4. Choose the directory that contains `plugin.json`.
5. Review the plugin metadata, valid skills, and diagnostics, then select **Add plugin**.

PostHog Desktop keeps a reference to the selected directory. When an agent session starts, it validates the plugin again and copies valid skill files into temporary app storage for that session. The temporary copy is removed when the session ends.

You can disable a plugin without removing it. Disabling a plugin stops its running stdio MCP servers but preserves its app-managed plugin data. Removing a plugin stops its stdio MCP servers and deletes its app-managed plugin data. It does not delete the source directory.

Adding a plugin approves the stdio command, arguments, environment values, and working directory shown in the preview. PostHog Desktop stores only a digest of each approved definition. If an executable definition is added or changed later, that server is skipped until you review the display-safe details and select **Approve stdio commands**. Environment values remain in the source `mcp.json` and are never returned to the app UI or stored in the installation registry.

## Supported format

A plugin must target Agent Plugins 1.0.0 and can provide Agent Skills in the standard location:

```text
my-plugin/
├── plugin.json
└── skills/
    └── summarize/
        └── SKILL.md
```

The manifest must include the canonical schema and a valid plugin name:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "my-plugin"
}
```

Each skill must follow the [Agent Skills specification](https://agentskills.io/specification). Invalid skills are skipped without disabling valid skills from the same plugin. Skill directories must contain only regular files and directories. Symbolic links are not loaded.

Session snapshots are limited to 256 files and 8 MiB per skill, with a 1 MiB limit for each file. A plugin can contribute up to 1,024 files and 32 MiB across its skill snapshots. Skills that exceed these limits are skipped.

Streamable HTTP MCP servers use the canonical MCP schema:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "example": {
      "type": "streamable-http",
      "url": "https://mcp.example.com/mcp"
    }
  }
}
```

Invalid MCP configuration does not disable valid skills. Each server is validated independently, so one invalid or unsupported server does not disable its valid siblings. PostHog Desktop follows same-origin redirects only. Configured header values stay in the privileged plugin loader and are not stored in the installation registry or returned to the app UI.

Stdio MCP servers can use a bare executable name or a bundled executable path beginning with `./`:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "local-tools": {
      "type": "stdio",
      "command": "./bin/server",
      "args": ["--data", "${PLUGIN_DATA}"],
      "env": {
        "CONFIG": "${PLUGIN_ROOT}/config.json"
      },
      "cwd": "${PLUGIN_ROOT}"
    }
  }
}
```

PostHog Desktop starts stdio commands without a shell and makes them available to Claude and Codex through a local managed bridge. The bridge binds to loopback, uses an unguessable route for each server, rejects browser requests, and limits request bodies. A server that fails to initialize or later disconnects is skipped or restarted without stopping sibling servers or skills. Running processes stop when the agent session ends, session startup fails, the plugin is disabled or removed, or the app shuts down.

Every installed plugin gets a stable writable `PLUGIN_DATA` directory. Its contents persist across plugin source updates and while the plugin is disabled. Removing the plugin deletes this directory. `PLUGIN_ROOT` points to the resolved source directory.

Only `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` are expanded, and only in `args`, `env` values, and `cwd`. Expansion is single-pass. The command is never expanded or interpreted as a shell command. Explicit working directories must remain within `PLUGIN_ROOT` or `PLUGIN_DATA`.

Stdio processes receive a minimal host environment needed to find executables and basic user directories. Configured `env` values are applied next, then PostHog Desktop sets `PLUGIN_ROOT` and `PLUGIN_DATA`. Other app environment variables and PostHog credentials are not inherited. Do not place secrets directly in `mcp.json` because it is visible plugin data.

## Current limitations

- Only local directory installation is available.
- Agent Skills, Streamable HTTP MCP servers, and stdio MCP servers are supported in Claude and Codex sessions.
- Legacy SSE MCP transport is skipped with a diagnostic.
- Agent Plugins does not define portable commands, hooks, or agents. PostHog Desktop does not load those components from a portable plugin.
- Plugin updates and registries are not supported. Edit or update the source directory directly.
