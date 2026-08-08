# Agent Plugins

PostHog Desktop supports skills from local [Agent Plugins 1.0.0](https://agent-plugins.org/).

## Add a local plugin

1. Open **Skills**.
2. Select the **Plugins** tab.
3. Select **Add local plugin**.
4. Choose the directory that contains `plugin.json`.
5. Review the plugin metadata, valid skills, and diagnostics, then select **Add plugin**.

PostHog Desktop keeps a reference to the selected directory. When an agent session starts, it validates the plugin again and copies valid skill files into temporary app storage for that session. The temporary copy is removed when the session ends.

You can disable a plugin without removing it. Removing a plugin only removes its registration from PostHog Desktop and does not delete the source directory.

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

Invalid MCP configuration does not disable valid skills. Each server is validated independently, so one invalid or unsupported server does not disable its valid siblings. PostHog Desktop reads up to 1 MiB from `mcp.json`. The loopback proxy accepts request bodies up to 2 MiB and returns an HTTP 413 response for larger requests. PostHog Desktop follows same-origin redirects only. Configured header values stay in the privileged plugin loader and are not stored in the installation registry or returned to the app UI.

## Current limitations

- Only local directory installation is available.
- Agent Skills are supported in Claude and Codex sessions.
- `mcp.json` is not loaded yet.
- Agent Plugins does not define portable commands, hooks, or agents. PostHog Desktop does not load those components from a portable plugin.
- Plugin updates and registries are not supported. Edit or update the source directory directly.
