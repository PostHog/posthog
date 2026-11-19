# Agent automation

When automating a convention, try these in order — only fall back to the next if the previous isn't suitable:

1. **Linters** (ruff, oxlint, semgrep) — code pattern enforcement, always paired with CI
2. **lint-staged / husky** — file-level validation or warnings at commit time
3. **Skills** (`.agents/skills/`) — scaffold with `hogli init:skill`
4. **AGENTS.md / CLAUDE.md instructions** — when automated enforcement isn't suitable

Claude Code hooks are reserved for environment bootstrapping (`SessionStart` only) — do not add `PreToolUse`, `PostToolUse`, or `Notification` hooks as they add latency and are fragile.
Changes to `.claude/hooks/` trigger a warning from the `pre-commit` hook; lint-staged allows only repo-wide keys in `.claude/settings.json`, because personal settings belong in the gitignored `.claude/settings.local.json`.
A warn-only check belongs in the `pre-commit` hook body rather than in a lint-staged task, because lint-staged discards the output of every task that exits 0.
