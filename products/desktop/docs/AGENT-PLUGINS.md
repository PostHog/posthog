# Agent Plugins

PostHog Desktop supports skills from local [Agent Plugins 1.0.0](https://agent-plugins.org/).

## Add a local plugin

1. Open **Skills**.
2. Select the **Plugins** tab.
3. Select **Add local plugin**.
4. Choose the directory that contains `plugin.json`.
5. Review the plugin metadata, valid skills, and diagnostics, then select **Add plugin**.

PostHog Desktop keeps a reference to the selected directory. It does not copy the plugin into the app. Changes on disk are validated again when an agent session starts.

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

Each skill must follow the [Agent Skills specification](https://agentskills.io/specification). Invalid skills are skipped without disabling valid skills from the same plugin.

## Current limitations

- Only local directory installation is available.
- Agent Skills are supported in Claude and Codex sessions.
- `mcp.json` is not loaded yet.
- Agent Plugins does not define portable commands, hooks, or agents. PostHog Desktop does not load those components from a portable plugin.
- Plugin updates and registries are not supported. Edit or update the source directory directly.
