---
description: Share current Claude Code session to PostHog/claude-sessions repo (private to PostHog org)
argument-hint: [optional description]
allowed-tools: Bash(python3 .claude/scripts/share-session.py:*)
---

Share the current Claude Code session log to the PostHog/claude-sessions private repository.

The session log will be converted to markdown format for better readability in GitHub's UI, including proper rendering of code blocks and mermaid diagrams. Only PostHog org members will have access.

## Usage

```bash
/share [optional description]
```

## Examples

```bash
/share
/share Working on feature flag refactoring
```

## Implementation

The command will:

1. Find the most recent session log from `~/.claude/projects/`
2. Convert JSONL format to readable markdown
3. Commit and push to PostHog/claude-sessions repo under `sessions/{your-username}/`
4. Return the GitHub URL (private to PostHog org)

## Execution

!`python3 .claude/scripts/share-session.py $ARGUMENTS`
