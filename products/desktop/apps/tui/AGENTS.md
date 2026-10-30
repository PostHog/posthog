# PostHog TUI (command centre)

An Ink terminal app for PostHog Tasks: a sidebar of your work, tmux-like split panes, and pi chats in the cloud or on this machine.
A chat runs pi, or Claude Code on the user's own Claude plan, here or in the cloud; Codex runs in the cloud on a ChatGPT plan. Other ACP logs are read for display only.

## What it does

- Sidebar: a Today row that opens the day's briefing in the main view (with its composer), split workspaces drawn as trees, each followed by a gap, then an All tasks list headed by the main view's new chat while it has one, that also holds the workspaces' tasks (their row there jumps to the pane), with run status dots, and keyboard or mouse selection.
- Search: a full-screen search over your tasks, each with its sidebar status and when it was last active.
- Panes: tmux-like splits, nested splits, focus by key or click, and a header with where the chat runs, its repo, its PR and its status.
- Cloud chats: transcripts stream from `CloudTaskEngine`, recent history preloads and older pages load on scroll up. The composer starts a run or continues one. A pane shows a new run's first message, the sandbox's setup steps as the backend reports them, and a failure reason. A reply to a stopped run brings the same run back.
- Local chats: pi runs on this machine through the desktop's pi client factory, with a task row on the server and a session file here. Agent dialogs and MCP permission requests are answered on the bottom sheet.
- Chat view: tool calls collapse into clickable summaries that highlight under the pointer, web links open on click, a drag selects and copies text, sent images list under their message, a compaction shows as its `/compact` and what it freed, and the agent's `show_actions` offers sit on the bottom sheet.
- Composer: slash commands with floating suggestions, `!` shell mode, pasted and dropped images, a message sent mid-turn steers the agent, a failed send goes back into the composer, Esc stops the agent and double Esc clears.
- Notices: a chat's notice sits right-aligned in a row kept above its composer. The composer's top rule shows the agent's background shells, the context donut and the cost.
- Sign-in from inside the app (OAuth, or a local dev login), with the layout saved between runs.
- Billing (`/billing`): who pays for new chats, saved between runs. PostHog runs pi on the gateway everywhere. ChatGPT runs pi on the GPT model here, after a browser login kept in pi's `~/.pi/agent/auth.json`, and Codex in the cloud on the account connected in Desktop. Anthropic runs Claude Code in the cloud with a `claude setup-token` token, pasted once in settings (Ctrl+; or `/settings`) and kept in `~/.config/posthog-tui/claude-token`; the TUI hands it to each run's sandbox when asked, so it must be open while a chat starts. A local chat on the Claude plan runs the user's own `claude` binary (the one `claude auth login` signed in) through the desktop app's agent service, so pi's `/model`, `/effort`, `/compact`, `!` and the cost donut are off on it.

## Run and test

- `pnpm dev` (from this folder) starts the app through Vite, so edits hot-reload into the running screen.
- Tests: `../../node_modules/.bin/vitest run` or `hogli test products/desktop/apps/tui`. Typecheck: `../../node_modules/.bin/tsc --noEmit -p .`.
- `@posthog/agent` and `@posthog/harness` resolve to their `dist/`. After changing them, rebuild with `pnpm --filter <package> build` (harness types: `pnpm build:types`).

In the app: Ctrl+\\ splits side by side and Ctrl+Shift+\\ (Ctrl+|) stacks, Cmd works in place of Ctrl, and legacy terminals send both as Ctrl+\\; Ctrl+C twice closes a chat, Ctrl+N starts a new chat (another pane inside a split workspace, the main view elsewhere), Ctrl+B (or Cmd+B, since tmux keeps Ctrl+B) narrows the sidebar to its logo, saved between runs, Ctrl+K (or Cmd+K) searches tasks, Ctrl+; opens settings, Ctrl+R reloads all code, Ctrl+Q quits.
Slash commands: `/model`, `/effort`, `/mode` (Claude Code chats: plan, auto, default...; the pick also sets the mode new Claude Code chats start in), `/compact [focus]`, `/new`, `/repo`, `/clear` (local chats), `/rename`, `/rename-workspace`, `/search`, `/settings`, `/billing`, `/local`, `/cloud`, `/login`, `/logout`, plus the live run's own commands. `/rename` and `/rename-workspace` with no name put the current one in the composer to edit.
`/new` in a split pane makes that pane a new chat. Anywhere else, `/new` and Ctrl+N clear the main view.
`/repo` opens a searchable multi-select of the GitHub repositories the team's and the user's GitHub connections reach (type to search, Space ticks, Enter saves). Each pane keeps its own pick for new cloud chats, saved between runs; a pane that never picked uses the repository of the folder the TUI started in.
`/local` and `/cloud` switch the current pane and set where new chats in other panes run, saved between runs.
`!` in an empty composer enters shell mode (orange `!` prompt and rule; Backspace on an empty command leaves it). Enter runs the command where the chat's agent runs (this machine or the sandbox), through pi's `bash` RPC, and adds its output to the agent's context.

## Where things live

Logic sits in plain modules with unit tests. Components under `src/components/` stay thin.

| Module | Owns |
| --- | --- |
| `cli.mjs`, `main.tsx` | Vite module runner, hot reload, terminal setup and teardown. A load that fails shows its error and keeps the process (and its local agents) alive; Enter tries again, and so does the next change to the code |
| `layout.ts` | Workspaces (splits only), the one main view, focus, new chats (`newChat`, `newChatIn`), persistence to one file per account, `~/.config/posthog-tui/layout.<account>.json` |
| `dividers.ts` | Split cell sizes and places, and the joined glyphs of the pane dividers and the sidebar's edge |
| `banner.ts` | What an empty chat shows above its composer: the model it starts on, who pays, and where it runs, from the pane's place, `/billing`, pi's starting model or the user's own `~/.claude/settings.json` |
| `prefs.ts` | Saved preferences in `~/.config/posthog-tui/prefs.json`: where new chats run by default, who pays for them, and the mode new Claude Code chats start in |
| `billing.ts`, `settings.ts`, `chatgpt.ts`, `claudeToken.ts`, `claudeLocal.ts` | The billing picker and what each billing starts (the cloud harness, the local model, or why a local chat cannot start); the settings screen's rows and keys; pi's ChatGPT login, logout and who is logged in; the Claude token file and the engine's store over it. `PiChats.start` takes the cloud harness, and `reply` continues pi, Claude and Codex runs. `LocalAgent` in `local.ts` is what a pane needs from any local agent: pi's `LocalSession`, or `ClaudeLocalSession`, which drives `AgentService` (built in `cloud.ts` with its Electron-only needs stubbed) and turns its ACP permission requests into `acp` prompts |
| `sidebar.ts` | Sidebar rows, cursor movement, status dots. A split task has two rows, so a workspace row's selection key is its pane |
| `search.ts` | The task search's result rows and query editing; `hooks/useSearch.ts` asks the server after a pause in typing |
| `turns.ts` | Which chats are mid-turn (the sidebar's spinner) and which finished while the reader was on another chat (the orange dot); a chat is watched from when it is on screen until its turn ends |
| `work.ts` | The Work list (`getTasksPage`), one request at a time |
| `runs.ts` | Cloud run views over `CloudTaskEngine`: tail windows, older pages, preloads, run notices. While a sandbox sets up, the notice names the backend's current setup step (`_posthog/progress`, group `setup:<runId>`). A pi task's runs share one pi session but keep separate logs, so its earlier runs page in above the current one |
| `chats.ts` | Starting and replying to pi cloud runs. A reply to a run that has ended or lost its sandbox brings the same run back with `resume_in_cloud`, as the desktop app does, waits for its agent (`CloudRuns.agentRestarted`), then sends; the pane says "Reopening sandbox…" until the backend's setup steps take over. If the server refuses, the reply starts a new run that continues it |
| `local.ts` | Local chats: the harness as a child process (`createPiRpcClient` + `PiRuntime`), with a pi session file each |
| `localChats.ts` | Local chats' pi session files under `~/.config/posthog-tui/local/`, one per task id, and linking older `local:<uuid>` files to new task rows |
| `models.ts` | `/model`, `/effort`, the run's slash commands and abort, over `pi/rpc` (cloud) or the local client |
| `transcript.ts` | Log entries to transcript lines, reusing the desktop's `buildConversationItems` |
| `chatView.ts`, `composer.ts` | pi-tui components rendered into panes: messages, scroll, editor, suggestions |
| `links.ts`, `openUrl.ts` | The web link under a clicked chat cell (OSC 8 or written out), opened in the browser; other schemes never open, and only a sent image the TUI saved opens as a file |
| `sheet.ts`, `actions.ts` | The reusable bottom sheet, and the agent's `show_actions` offers on it |
| `picker.ts`, `hooks/useRepoPicker.ts` | A searchable multi-select drawn in place of the composer, and `/repo` on it: per-pane picks in `prefs.json`, searches through `PiChats.searchRepositories` |
| `prompts.ts` | A local agent's dialogs and MCP permission requests, shown on the sheet and answered through the pi extension response |
| `status.ts` | The PR and status chips in the pane header |
| `usage.ts` | The agent's background shells and monitors (its `background-shells` status), the context donut, and the task cost at the right end of the composer's top rule |
| `theme.ts`, `faint.ts` | Light or dark from the terminal's OSC 11 background reply, kept live through mode 2031 reports; fills tinted from that background; PostHog blue; and the dimming of unfocused panes |
| `mouse.ts`, `shortcuts.ts` | Raw input: mouse reports, app keys, kitty and legacy key forms |
| `shell.ts` | `!` commands: reading them from the composer, and the log entries that show a run before pi's saved conversation has it |
| `selection.ts`, `clipboard.ts`, `highlight.ts` | Click or drag: a press and release on one cell clicks (in the composer it places the cursor), and a drag selects chat or composer text and copies it on release |
| `images.ts` | Images for any chat: Ctrl+V reads the clipboard's image (macOS), a dropped image file is read from its pasted path, and the composer shows each as an `[Image #n]` marker. A sent image is saved under `~/.config/posthog-tui/images/` by a hash of its bytes, and its row under the message opens it. A cloud run gets them uploaded as artifacts (`ImageUploads` in `chats.ts`, the desktop app's `CloudArtifactService`), and its sandbox hands them to pi as image data |
| `auth.ts`, `cloud.ts` | OAuth tokens and the engine, API client and local-session wiring |
| `errors.ts`, `components/ErrorBoundary.tsx` | `messageOf` for notices, `LOG_PATH` and `logError`; the boundary that shows a render error in place of the app instead of ending the process |
| `components/App.tsx`, `components/PaneTree.tsx` | Wiring the hooks together, and drawing the sidebar and the split panes |
| `hooks/` | App state, one hook per concern: notices (a chat's notice wraps, right-aligned, in a row kept above its composer, and falls back to the sidebar while no pane shows the chat; app-wide ones stay in the sidebar), work list, local chats, pane views, sheets, models, `!` commands, sending, sidebar, search, turns, keys, pointer, terminal input |

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
- **An agent editing the TUI from inside it reloads the app it runs in, mid-edit.** Every saved file hot-reloads, and a local agent's session lives in that process. Write each step so the app still loads and renders: add a module or export before the code that imports it, and make a callee accept a new argument before its caller passes it (and the reverse when removing). A step that broke this ended the session before `ErrorBoundary` and the `cli.mjs` recovery; now it shows an error screen, and the TUI reloads by itself when the next change loads.
- **The engine stops watching a run once it ends.** A run brought back with `resume_in_cloud` keeps its id, so the pane's watch never re-subscribes. `CloudRuns.agentRestarted` watches it again, and a newer copy of the same run in `fresh` wins over the work list (`findTask` compares `updated_at`).
- **The backend fails a cloud run whose pi turn ends with `stopReason: "error"`, and destroys its sandbox.** An Esc can cut off a model request that then reports an error. The agent's translator ends such a turn as cancelled (`translatePiConversation.ts`); a cloud sandbox only gets that fix with a new `@posthog/agent` release.
- **Local agents live in a global map keyed by task id**, so they survive hot reloads. In tests, give each local chat its own task id, or a later test gets an earlier test's agent.
- **Local Docker sandboxes need the agent-server bundle linked**, or the pi capability probe fails. See `products/tasks/backend/sandbox/images/Dockerfile.sandbox-local`.

## Open ends

- Before a run exists, `/` lists only the built-in commands. The plan is bundled skills and the repo's `.claude/skills` from disk, then user skills with the desktop's upload step.
- A local chat has a task row but no run, and its conversation lives only in its pi session file on this machine. The server hears nothing about local activity, so the sidebar sorts local chats by their session file's last change.
- The desktop app keeps its own local pi session files, so a TUI local chat opened there shows no conversation, and the reverse.
- Cloud sandboxes run the published `@posthog/agent`. Harness and agent changes on this branch (background shells, compaction details, the aborted-turn fix) reach cloud chats only after they land on master and the sandbox image picks up the release.
- No analytics or error tracking yet. The plan is the desktop app's PostHog project, with an `app: "tui"` property, and no message content.
- pi chats have no auto, manual or plan modes: pi has none, and the harness adds none. `/mode` works on local Claude Code chats only. The desktop app's embedded chat view shows Claude's mode picker on pi chats, and it does nothing there.
- A cloud sandbox stops when idle, and its background shells stop with it.
- Long cloud pi chats stop taking messages. Before a follow-up, the backend rebinds the sandbox's MCP credentials once its binding marker expires (half the token lifetime), and the pi agent server has no `refresh_session` command, so the backend fails the delivery closed. The TUI shows the failed `followup_delivery` step and puts the message back (`deliveryFailure` in `runs.ts`); the fix is `refresh_session` in the pi agent server.
