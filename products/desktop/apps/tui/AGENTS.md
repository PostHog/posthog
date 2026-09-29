# PostHog TUI (command centre)

An Ink terminal app for PostHog Tasks: a sidebar of your work, tmux-like split panes, and pi chats in the cloud or on this machine.
pi is the only harness it starts or talks to. ACP logs (Claude, Codex) are read for display only.

## Run and test

- `pnpm dev` (from this folder) starts the app through Vite, so edits hot-reload into the running screen.
- Tests: `../../node_modules/.bin/vitest run` or `hogli test products/desktop/apps/tui`. Typecheck: `../../node_modules/.bin/tsc --noEmit -p .`.
- `@posthog/agent` and `@posthog/harness` resolve to their `dist/`. After changing them, rebuild with `pnpm --filter <package> build` (harness types: `pnpm build:types`).
- `pnpm-lock.yaml` has no entry for this app yet: `pnpm install` failed in the session that built it, and the hoisted workspace `node_modules` covered every dependency.

In the app: Ctrl+S and Ctrl+Shift+S (or Ctrl+\\) split, Ctrl+C twice closes a chat, Ctrl+N starts a new chat, Ctrl+R reloads all code, Ctrl+Q quits.
Slash commands: `/model`, `/new`, `/local`, `/cloud`, `/login`, `/logout`, plus the live run's own commands.

## Where things live

Logic sits in plain modules with unit tests. Components under `src/components/` stay thin.

| Module | Owns |
| --- | --- |
| `cli.mjs`, `main.tsx` | Vite module runner, hot reload, terminal setup and teardown |
| `layout.ts` | Workspaces (splits only), the one main view, focus, persistence to `~/.config/posthog-tui/layout.json` |
| `sidebar.ts` | Sidebar rows, cursor movement, status dots |
| `work.ts` | The Work list (`getTasksPage`), one request at a time |
| `runs.ts` | Cloud run views over `CloudTaskEngine`: tail windows, older pages, preloads, run notices |
| `chats.ts` | Starting and replying to pi cloud runs |
| `local.ts` | Local chats: the harness as a child process (`createPiRpcClient` + `PiRuntime`), with a pi session file each |
| `models.ts` | `/model`, the run's slash commands and abort, over `pi/rpc` (cloud) or the local client |
| `transcript.ts` | Log entries to transcript lines, reusing the desktop's `buildConversationItems` |
| `chatView.ts`, `composer.ts` | pi-tui components rendered into panes: messages, scroll, editor, suggestions |
| `sheet.ts`, `actions.ts` | The reusable bottom sheet, and the agent's `show_actions` offers on it |
| `mouse.ts`, `shortcuts.ts` | Raw input: mouse reports, app keys, kitty and legacy key forms |
| `auth.ts`, `cloud.ts` | OAuth tokens and the engine, API client and local-session wiring |

## Things that bit us

- **Tests and smoke runs never touch the real `~/.config/posthog-tui`.** `vitest.config.ts` sets a temp `HOME`. Drive the app in a pty with a temp `HOME` too, or a run can overwrite the user's session and layout.
- **Ink draws an empty string with no height.** A blank row must carry a space, as `ChatView.render` does.
- **Flex layout rounds half rows and leaves gaps.** Splits get whole-cell sizes from `splitSizes`, and a split with its own divider sizes its children inside that divider.
- **Ink enters the alternate screen without moving the cursor home.** The full-height root box is what makes it draw from the top.
- **A Vite full reload skips `dispose`.** `main.tsx` also tears down on `vite:beforeFullReload`, and a disposed `MouseInput` no longer switches raw mode, or the old copy turns it off under the new one. Ctrl+R triggers a full reload through `globalThis.__posthogTuiReload`, set in `cli.mjs`.
- **The commit hook runs `biome check --write --unsafe`.** Its exhaustive-deps fix once added a whole task object to a `useEffect` and re-subscribed every 10 seconds. Key effects on ids, or call changing functions through a ref.
- **`MouseInput` sits between the terminal and Ink.** It strips mouse reports and hands raw keys to the app, which splits them with pi's `StdinBuffer`. App keys (`isAppKey`) go to Ink handlers, and everything else goes to the focused composer or an open sheet.
- **pi components pad for a full screen.** `ChatView` trims their blank edges, strips OSC 133 marks, and spaces blocks itself.
- **Local Docker sandboxes need the agent-server bundle linked**, or the pi capability probe fails. See `products/tasks/backend/sandbox/images/Dockerfile.sandbox-local`.

## Open ends

- Local chats pass the TUI's OAuth token to the gateway. A real local run had not been tried when this was written.
- Before a run exists, `/` lists only the built-in commands. The plan is bundled skills and the repo's `.claude/skills` from disk, then user skills with the desktop's upload step.
- Local chats are not in the Work list; they live in the layout and their pi session files under `~/.config/posthog-tui/local/`.
- Divider corners do not join. Box borders cannot place junctions; drawing dividers from the computed sizes would.
