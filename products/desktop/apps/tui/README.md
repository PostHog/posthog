# PostHog TUI

A terminal command centre for PostHog tasks: your tasks in a sidebar, tmux-like split panes, and agent chats that run in a cloud sandbox or on this machine.

## Install

```sh
npm i -g @posthog/tui     # or: posthog-cli code
```

Node 22.19 or newer. Put `claude` on PATH to run Claude Code locally on your own plan.

The first run signs you in to PostHog, then asks who pays for chats. Pick PostHog to start with no other login.

To work on it from the repo, in the monorepo's flox environment:

```sh
cd products/desktop && pnpm install && pnpm build:agent
cd apps/tui && pnpm dev        # Vite, hot reload
# or: pnpm build && pnpm start  # the bundle npm ships
```

## Who pays

`/billing` picks it, for cloud and local chats alike. Chats already open keep their agent.

| Plan | Locally | In the cloud |
| --- | --- | --- |
| PostHog | pi on the gateway | pi on the gateway |
| ChatGPT | pi on GPT, after a browser login | Codex, on the ChatGPT account connected to PostHog (a second login, since PostHog keeps its own tokens) |
| Anthropic | your own `claude` binary | Claude Code, on a `claude setup-token` token the app hands to the sandbox; keep the app open while a run starts |

Picking a plan that lacks its login runs the sign-in on a sheet. Settings (Ctrl+;) holds the logins and the Claude token.

## Around the app

- Sidebar: Today opens the day's briefing. Workspaces draw as trees above All chats. A spinner is a chat mid-turn, orange a turn that finished while you were elsewhere, a cross a failed run.
- Panes: split, nest, focus by key or click. The header shows where the chat runs, its repo and its PR.
- Chats: a reply to a finished cloud run brings the same run back. Tool calls collapse into clickable rows, links open, a drag copies.
- Composer: `/` for commands, `!` for a shell command where the agent runs, Ctrl+V or a file drop for images. A message sent mid-turn steers the agent.
- Search: Ctrl+K, full screen or in an empty split pane, where the pick fills that pane.
- MCP: `/mcp` lists your servers, adds one, and can relay local servers into cloud runs.

## Keyboard shortcuts

| Keys | Does |
| --- | --- |
| Ctrl+N | New chat: in the focused pane of a split, else the main view |
| Ctrl+Shift+N | New chat in the main view, outside the split |
| Ctrl+K | Search chats |
| Ctrl+Shift+K | Search full screen, even from a split |
| Ctrl+C Ctrl+C | Close the chat; on the last pane, quit (Ctrl+D too) |
| Esc | Stop the agent; twice clears, or brings back the chat an empty new chat replaced |
| Ctrl+V | Paste an image |
| `!` | Run a shell command where the agent runs |
| Ctrl+\ / Ctrl+\| | Split side by side / stacked |
| Tab / Shift+Tab | Next pane or the sidebar / back |
| ↑ ↓ ← → | Step chats / fold a workspace |
| Ctrl+[ / Ctrl+] | Back / forward through the chats visited (Ctrl+[ needs a kitty terminal) |
| Ctrl+M / Ctrl+Shift+M | Step a Claude Code chat's mode / back (kitty terminals) |
| Ctrl+B | Narrow the sidebar |
| Ctrl+P | Pin or unpin a chat above the workspaces |
| Ctrl+; | Settings |
| Ctrl+R / Ctrl+Q | Reload / quit |

Cmd works in place of Ctrl where the terminal passes it on.

## Slash commands

| Command | Does |
| --- | --- |
| `/model`, `/effort` | Switch this chat's model, and how much it thinks |
| `/mode` | Switch a Claude Code chat's permission mode (plan, auto, default, bypass) |
| `/compact [focus]` | Summarize older messages to free up context |
| `/billing` | Choose who pays for new chats |
| `/new` | Start a new chat: in the focused pane of a split, else the main view |
| `/rename`, `/rename-workspace` | Rename this chat or workspace; with no name, edit the current one |
| `/optimize` | Lay out this workspace's panes in an even grid |
| `/expand` | Open this chat full width |
| `/search` | Search your tasks |
| `/local`, `/cloud` | Run this pane's new chats on this machine or in the cloud |
| `/repo` | Pick the repositories this pane's new cloud chats clone |
| `/mcp`, `/mcp add` | The MCP servers your chats reach, and add one |
| `/clear` | Clear this local chat's conversation |
| `/settings` (or `/config`) | Open settings |
| `/help` | Every shortcut, full screen |
| `/login`, `/logout` | Sign in to PostHog, or out; workspaces stay |

A live run's own commands (skills, prompt templates) join the list.

## Where things are kept

`~/.config/posthog-tui/` holds the sign-in, preferences, one layout per account, local chat sessions, sent images and the Claude token. The log is `posthog-tui.log` in the OS temp dir. To see the first run again, start with another home: `HOME=$(mktemp -d) pnpm dev`.
