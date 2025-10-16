# Share Script

Share Claude Code session logs to the PostHog/claude-sessions private repository.

## Usage

Via the `/share` slash command:

```bash
/share                           # Default: timestamp-only filename
/share working on feature flags  # Custom: timestamp-working-on-feature-flags.md
```

Or directly:

```bash
python3 .claude/scripts/share/share.py [description]
```

## How it works

1. Finds the most recent session log from `~/.claude/projects/`
2. Converts JSONL format to readable markdown
3. Commits and pushes to `PostHog/claude-sessions` under `sessions/{your-username}/`
4. Returns the GitHub URL (private to PostHog org)

## Filename format

- Without description: `YYYYMMDD-HHMMSS.md`
- With description: `YYYYMMDD-HHMMSS-sanitized-description.md`

Descriptions are sanitized (spaces to hyphens, alphanumeric only, max 50 chars).

## Testing

```bash
pytest .claude/scripts/share/test_share.py
```
