# Cleanup

Use this reference after the final report is written and any approved PR comment, upload, or push handling is complete.

It also applies to every early exit. If the run aborts at any point after a checkout happened, a browser session opened, or generated local config appeared, still restore the original branch, close the browser session, and remove agent-generated hunks before returning. A skipped cleanup leaves a dirty tree that blocks the next PR-mode run at its clean-tree gate.

## Checkout

PR mode always attempts to restore the original branch:

```bash
git checkout "$original_branch"
```

If the run started from a detached HEAD, `$original_branch` is the SHA recorded at preflight; never run `git checkout` with an empty argument.

Leave `.qa-frontend/runs/<run-id>/` in place for debugging unless the user asked for cleanup. Confirm `git status --porcelain` is clean except for intentional local fix commits that could not be pushed because the push was rejected or connectivity failed.

Local mode did not check out a PR branch, so there is nothing to restore. Leave the run directory in place.

## Overrides

If the run set a theme override or feature-flag overrides, restore them (theme back to the original `theme_mode`, `overrideFeatureFlags(false)`) before closing the browser session, as the matching sections in `browser-mcp-patterns.md` describe.

## Browser Session

After the final report is written, end the browser automation session if the browser MCP/tooling exposes a close-page, close-context, close-browser, or end-session action. This prevents stale Chromium sessions from blocking later QA runs.

Do not close the user's visible browser windows. If a stale headless Chromium process from a previous agent blocks the run and no MCP close action is available, ask the user before killing it, and target only agent-started browser processes. Agent-started browser processes commonly include command-line markers such as `ms-playwright`, `mcp-chrome-`, `remote-debugging-pipe`, or `playwright-mcp`; visible user browsers usually use the normal browser profile instead. If you inspect processes, use these markers to explain exactly what you plan to terminate before asking for approval.

## Stack

If `STACK_STARTED_BY_AGENT=1`, stop only the stack the agent started during cleanup unless the user explicitly asked to keep it running. Use the matching repo-recommended stop command for the approved startup path. For example, when the approved startup path was `bin/hogli up -d`, stop it with:

```bash
bin/hogli down -y
```

If the user started the stack themselves, do not stop or restart it without explicit approval.

## Generated Local Files

If `hogli` auto-adds a local `phrocs` command to `hogli.yaml`, remove only that generated hunk during cleanup. Do not commit it as part of a QA run.
