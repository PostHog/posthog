# Coder Workspaces

PostHog has an internal Coder deployment for cloud-hosted development workspaces.
Use this when you want a remote PostHog dev environment instead of running the full stack on your laptop.

## When to use it

- You want an isolated workspace for agentic or local development
- Your laptop does not have enough CPU, memory, or disk for local development
- You want a persistent remote workspace that is easy to stop and resume
- You are working from a machine where local Docker setup is inconvenient

## Prerequisites

- Access to the PostHog Tailscale tailnet (on macOS, the Tailscale app bundle CLI is detected automatically if `tailscale` isn't on PATH)
- Access to the internal Coder deployment at `https://coder.hedgehog-kitefin.ts.net`
- `hogli` available locally

## First-time setup

Run:

```bash
hogli devbox:setup
```

This does the host-side setup only:

- verifies Tailscale connectivity
- installs the `coder` CLI with Homebrew if needed
- logs you into the Coder deployment
- configures `~/.ssh/config` with Coder workspace entries (use `--skip-configure-ssh` to skip)
- prompts for Git identity (name and email) for workspace commits
- prompts for an optional dotfiles repo URL to personalize workspaces
- prompts for an optional Claude OAuth token, cached in macOS Keychain
- prints a setup summary with reconfiguration commands

To reconfigure individual settings later, pass the corresponding flag:

```bash
hogli devbox:setup --configure-git-identity
hogli devbox:setup --configure-dotfiles
hogli devbox:setup --configure-claude
```

## Available commands

Run:

```bash
hogli devbox
```

Then use `hogli <command> --help` for command-specific options.

Key commands include:

| Command               | Description                                            |
| --------------------- | ------------------------------------------------------ |
| `devbox:setup`        | Install and configure local access to Coder devboxes   |
| `devbox:start`        | Start or create your remote devbox                     |
| `devbox:stop`         | Stop your devbox (preserves disk, stops billing)       |
| `devbox:restart`      | Restart your devbox                                    |
| `devbox:update`       | Update devbox to the latest template                   |
| `devbox:list`         | List your devboxes                                     |
| `devbox:ssh`          | SSH into your devbox                                   |
| `devbox:open`         | Open devbox in browser, VS Code, or Cursor             |
| `devbox:logs`         | Tail devbox build and agent logs                       |
| `devbox:forward`      | Forward PostHog UI to localhost                        |
| `devbox:status`       | Show devbox status                                     |
| `devbox:destroy`      | Destroy your devbox and its data                       |
| `devbox:cleanup:disk` | Free disk space by cleaning caches and build artifacts |

`devbox:open` supports `--vscode`, `--cursor`, and `--web` flags. For example, to open a workspace in Cursor:

```bash
hogli devbox:open --cursor
```

If your template includes the Claude module, `devbox:start` can prompt for a Claude OAuth token when the workspace is created. On macOS, the token is cached in Keychain and reused automatically. Pass `--configure-claude` to replace a cached token.
After connecting with `hogli devbox:ssh`, run `claude` directly in the workspace terminal.

Runtime commands assume setup is already complete.
If they fail with `Run hogli devbox:setup`, rerun setup on your laptop first.

## Auth model

- Laptop to workspace access uses `coder ssh` and `coder config-ssh` (configured automatically during setup)
- Git inside the workspace should use HTTPS via Coder external auth
- Do not set up SSH Git inside the workspace
- Claude auth for the workspace is passed through the `claude_oauth_token` Coder parameter, not AI Bridge. On macOS, the token is cached in Keychain.

`go/coder` is a convenient shortcut for humans, but the canonical deployment URL is `https://coder.hedgehog-kitefin.ts.net`.
