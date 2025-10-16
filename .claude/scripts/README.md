# Claude Code Scripts

Utility scripts for Claude Code slash commands.

## Available Scripts

### share

Share Claude Code session logs to PostHog/claude-sessions private repository.

**Usage:**

```bash
/share [optional description]
```

See [share/README.md](share/README.md) for details.

## Adding New Scripts

1. Create a new directory under `.claude/scripts/` (e.g., `my-script/`)
2. Add your Python script with a `main()` function
3. Add tests in the same directory
4. Create a slash command in `.claude/commands/` that calls your script
5. Add a README documenting usage and behavior
