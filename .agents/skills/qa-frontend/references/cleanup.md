# Cleanup

Use this reference after the final report is written and any approved PR comment,
upload, or push handling is complete.

## Checkout

PR mode always attempts to restore the original branch:

```bash
git checkout "$original_branch"
```

Leave `.qa-frontend/runs/<run-id>/` in place for debugging unless the user asked
for cleanup. Confirm `git status --porcelain` is clean except for intentional
local fix commits that could not be pushed due to a connectivity or lease
failure.

Local mode did not check out a PR branch, so there is nothing to restore. Leave
the run directory in place.

## Browser Session

After the final report is written, end the browser automation session if the
browser or Playwright MCP exposes a close-page, close-context, close-browser, or
end-session action. This prevents stale Chromium sessions from blocking later QA
runs.

Do not close the user's visible browser windows. If a stale headless Chromium
process from a previous agent blocks the run and no MCP close action is
available, ask the user before killing it, and target only agent-started browser
processes. Agent-started browser processes commonly include command-line markers
such as `ms-playwright`, `mcp-chrome-`, `remote-debugging-pipe`, or
`playwright-mcp`; visible user browsers usually use the normal browser profile
instead. If you inspect processes, use these markers to explain exactly what you
plan to terminate before asking for approval.

## Stack

If `STACK_STARTED_BY_AGENT=1`, stop only the stack the agent started during
cleanup unless the user explicitly asked to keep it running. Use the matching
repo-recommended stop command for the approved startup path. For example, when
the approved startup path was `bin/hogli up -d`, stop it with:

```bash
bin/hogli down -y
```

If the user started the stack themselves, do not stop or restart it without
explicit approval.

## Generated Local Files

If `hogli` auto-adds a local `phrocs` command to `hogli.yaml`, remove only that
generated hunk during cleanup. Do not commit it as part of a QA run.
