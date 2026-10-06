# PostHog TUI (command centre)

An Ink terminal app for PostHog Tasks: a sidebar of your work, tmux-like split panes, and pi chats in the cloud or on this machine.
pi is the only harness it starts or talks to. ACP logs (Claude, Codex) are read for display only.

## What it does

- Sidebar: split workspaces drawn as trees, each followed by a gap, then an All tasks list with run status dots, and keyboard or mouse selection.
- Search: a full-screen search over your tasks, each with its sidebar status and when it was last active.
- Panes: tmux-like splits, nested splits, focus by key or click, and a header with where the chat runs, its repo, its PR and its status.
- Cloud chats: transcripts stream from `CloudTaskEngine`, recent history preloads and older pages load on scroll up. The composer starts a run or continues one, and a pane shows a new run's first message, start-up state and failure reason.
- Local chats: pi runs on this machine through the desktop's pi client factory, with a task row on the server and a session file here. Agent dialogs and MCP permission requests are answered on the bottom sheet.
- Chat view: tool calls collapse into clickable summaries that highlight under the pointer, web links open on click, a drag selects and copies text, and the agent's `show_actions` offers sit on the bottom sheet.
- Composer: `/model`, `/effort`, the live run's own slash commands, floating suggestions, `!` shell mode, Esc to stop the agent and double Esc to clear.
- Sign-in from inside the app (OAuth, or a local dev login), with the layout saved between runs.

## Run and test

- `pnpm dev` (from this folder) starts the app through Vite, so edits hot-reload into the running screen.
- Tests: `../../node_modules/.bin/vitest run` or `hogli test products/desktop/apps/tui`. Typecheck: `../../node_modules/.bin/tsc --noEmit -p .`.
- `@posthog/agent` and `@posthog/harness` resolve to their `dist/`. After changing them, rebuild with `pnpm --filter <package> build` (harness types: `pnpm build:types`).

In the app: Ctrl+\\ splits side by side and Ctrl+Shift+\\ (Ctrl+|) stacks, Cmd works in place of Ctrl, and legacy terminals send both as Ctrl+\\; Ctrl+C twice closes a chat, Ctrl+N starts a new chat, Ctrl+B (or Cmd+B, since tmux keeps Ctrl+B) narrows the sidebar to its logo, saved between runs, Ctrl+K (or Cmd+K) searches tasks, Ctrl+R reloads all code, Ctrl+Q quits.
Slash commands: `/model`, `/effort`, `/compact`, `/new`, `/rename`, `/rename-workspace`, `/search`, `/local`, `/cloud`, `/login`, `/logout`, plus the live run's own commands. `/rename` and `/rename-workspace` with no name put the current one in the composer to edit.
`/local` and `/cloud` switch the current pane and set where new chats in other panes run, saved between runs.
`!` in an empty composer enters shell mode (orange `!` prompt and rule; Backspace on an empty command leaves it). Enter runs the command where the chat's agent runs (this machine or the sandbox), through pi's `bash` RPC, and adds its output to the agent's context.

## Where things live

Logic sits in plain modules with unit tests. Components under `src/components/` stay thin.

| Module | Owns |
| --- | --- |
| `cli.mjs`, `main.tsx` | Vite module runner, hot reload, terminal setup and teardown |
| `layout.ts` | Workspaces (splits only), the one main view, focus, persistence to one file per account, `~/.config/posthog-tui/layout.<account>.json` |
| `dividers.ts` | Split cell sizes and places, and the joined glyphs of the pane dividers and the sidebar's edge |
| `prefs.ts` | Saved preferences in `~/.config/posthog-tui/prefs.json`: where new chats run by default |
| `sidebar.ts` | Sidebar rows, cursor movement, status dots |
| `search.ts` | The task search's result rows and query editing; `hooks/useSearch.ts` asks the server after a pause in typing |
| `turns.ts` | Which chats are mid-turn (the sidebar's spinner) and which finished while the reader was on another chat (the orange dot); a chat is watched from when it is on screen until its turn ends |
| `work.ts` | The Work list (`getTasksPage`), one request at a time |
| `runs.ts` | Cloud run views over `CloudTaskEngine`: tail windows, older pages, preloads, run notices. A pi task's runs share one pi session but keep separate logs, so its earlier runs page in above the current one |
| `chats.ts` | Starting and replying to pi cloud runs |
| `local.ts` | Local chats: the harness as a child process (`createPiRpcClient` + `PiRuntime`), with a pi session file each |
| `localChats.ts` | Local chats' pi session files under `~/.config/posthog-tui/local/`, one per task id, and linking older `local:<uuid>` files to new task rows |
| `models.ts` | `/model`, `/effort`, the run's slash commands and abort, over `pi/rpc` (cloud) or the local client |
| `transcript.ts` | Log entries to transcript lines, reusing the desktop's `buildConversationItems` |
| `chatView.ts`, `composer.ts` | pi-tui components rendered into panes: messages, scroll, editor, suggestions |
| `links.ts`, `openUrl.ts` | The web link under a clicked chat cell (OSC 8 or written out), opened in the browser; other schemes never open, and only a sent image the TUI saved opens as a file |
| `sheet.ts`, `actions.ts` | The reusable bottom sheet, and the agent's `show_actions` offers on it |
| `prompts.ts` | A local agent's dialogs and MCP permission requests, shown on the sheet and answered through the pi extension response |
| `status.ts` | The PR and status chips in the pane header |
| `usage.ts` | The agent's background shells and monitors (its `background-shells` status), the context donut, and the task cost at the right end of the composer's top rule |
| `theme.ts`, `faint.ts` | Light or dark from the terminal's OSC 11 background reply, and the dimming of unfocused panes |
| `mouse.ts`, `shortcuts.ts` | Raw input: mouse reports, app keys, kitty and legacy key forms |
| `shell.ts` | `!` commands: reading them from the composer, and the log entries that show a run before pi's saved conversation has it |
| `selection.ts`, `clipboard.ts`, `highlight.ts` | Click or drag: a press and release on one cell clicks (in the composer it places the cursor), and a drag selects chat or composer text and copies it on release |
| `images.ts` | Images for any chat: Ctrl+V reads the clipboard's image (macOS), a dropped image file is read from its pasted path, and the composer shows each as an `[Image #n]` marker. A sent image is saved under `~/.config/posthog-tui/images/` by a hash of its bytes, and its row under the message opens it. A cloud run gets them uploaded as artifacts (`ImageUploads` in `chats.ts`, the desktop app's `CloudArtifactService`), and its sandbox hands them to pi as image data |
| `auth.ts`, `cloud.ts` | OAuth tokens and the engine, API client and local-session wiring |
| `components/App.tsx`, `components/PaneTree.tsx` | Wiring the hooks together, and drawing the sidebar and the split panes |
| `hooks/` | App state, one hook per concern: notices, work list, local chats, pane views, sheets, models, `!` commands, sending, sidebar, search, turns, keys, pointer, terminal input |

## Things that bit us

- **Tests and smoke runs never touch the real `~/.config/posthog-tui`.** `vitest.config.ts` sets a temp `HOME`. Drive the app in a pty with a temp `HOME` too, or a run can overwrite the user's session and layout.
- **Ink draws an empty string with no height.** A blank row must carry a space, as `ChatView.render` does.
- **Flex layout rounds half rows and leaves gaps.** Splits get whole-cell sizes from `splitSizes`, and a split with its own divider sizes its children inside that divider.
- **Ink enters the alternate screen without moving the cursor home.** The full-height root box is what makes it draw from the top.
- **A Vite full reload skips `dispose`.** `main.tsx` also tears down on `vite:beforeFullReload`, and a disposed `MouseInput` no longer switches raw mode, or the old copy turns it off under the new one. Ctrl+R triggers a full reload through `globalThis.__posthogTuiReload`, set in `cli.mjs`.
- **The commit hook runs `biome check --write --unsafe`.** Its exhaustive-deps fix once added a whole task object to a `useEffect` and re-subscribed every 10 seconds. Key effects on ids, or call changing functions through a ref.
- **`MouseInput` sits between the terminal and Ink.** It strips mouse reports and hands raw keys to the app, which splits them with pi's `StdinBuffer`. App keys (`isAppKey`) go to Ink handlers, and everything else goes to the focused composer or an open sheet.
- **pi components pad for a full screen.** `ChatView` trims their blank edges, strips OSC 133 marks, and spaces blocks itself.
- **A dropped file arrives as a paste of its path, with no position.** Ghostty reports the pointer a few milliseconds before the paste, so `paneAtDrop` sends the path to the pane under it. Terminals with kitty's OSC 72 drag-and-drop protocol report the drop point itself; the TUI does not use it yet.
- **Local Docker sandboxes need the agent-server bundle linked**, or the pi capability probe fails. See `products/tasks/backend/sandbox/images/Dockerfile.sandbox-local`.

## Open ends

- Before a run exists, `/` lists only the built-in commands. The plan is bundled skills and the repo's `.claude/skills` from disk, then user skills with the desktop's upload step.
- A local chat has a task row but no run, and its conversation lives only in its pi session file on this machine. The server hears nothing about local activity, so the sidebar sorts local chats by their session file's last change.
- The desktop app keeps its own local pi session files, so a TUI local chat opened there shows no conversation, and the reverse.
