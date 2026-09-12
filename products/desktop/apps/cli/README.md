# hog-tui prototype

`hog-tui` is an OpenTUI terminal interface for the PostHog harness.

## Requirements

- Node.js 26.4.0 or later. `hog-tui` restarts itself with Node's `--experimental-ffi` flag.
- An existing harness login. Run `hog /login` before starting `hog-tui`.

## Run

From `products/desktop/`:

```sh
pnpm --filter @posthog/cli build
pnpm --filter @posthog/cli start
```

Use `hog-tui --cwd <path>` to set the working directory. Use `hog-tui --continue` to continue the most recent session for that directory.

## Controls

- Enter sends the prompt.
- Shift+Enter inserts a new line.
- Ctrl+C stops the active turn. Ctrl+C exits when the session is idle.

The prompt supports the standard harness tools, prompts, skills, MCP servers, and Pi session commands.

## Prototype limits

Interactive extension dialogs are not part of this prototype. Desktop-only task context is not part of this prototype.
