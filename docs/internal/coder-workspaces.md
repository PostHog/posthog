# Coder Workspaces

PostHog has an internal Coder deployment for cloud-hosted development workspaces.
Use this when you want a remote PostHog dev environment instead of running the full stack on your laptop.

## When to use it

- You want an isolated workspace for agentic or local development
- Your laptop does not have enough CPU, memory, or disk for local development
- You want a persistent remote workspace that is easy to stop and resume
- You are working from a machine where local Docker setup is inconvenient

## Common scenarios

**Connecting your IDE** —
Open the workspace in VS Code (`hogli devbox:open --vscode`), Cursor (`--cursor`), or a browser-based editor (`--web`).

**Running a background agent task** —
Spin up a fresh devbox that runs a coding agent against a prompt, without taking over your current session:

```bash
hogli devbox:task "fix CI on PR #1234"
cat prompt.txt | hogli devbox:task       # or pipe the prompt via stdin
```

See the upstream [Coder Tasks docs](https://coder.com/docs/ai-coder/tasks) for the execution model.

**Running the dev stack in detached mode** —
Start the PostHog dev stack in the background without an interactive terminal:

```bash
hogli up -d          # start in detached mode
hogli wait           # block until all services are ready
hogli down           # gracefully stop the stack
```

`hogli start -d` and `hogli stop` are also available as equivalents. This is useful when you want to run the dev stack as a background process while using your terminal for other work, or when launching from scripts and automation.

**Sharing a workspace** —
Grant a teammate access for pair debugging or to pick up where you left off:

```bash
hogli devbox:users                          # list Coder usernames
hogli devbox:share bob-box --user alice     # grant access (default role: use)
hogli devbox:unshare bob-box --user alice   # revoke access
hogli devbox:share bob-box --list           # see who has access
```

Once shared, the teammate can target your workspace with `@user[/label]` syntax (e.g. `hogli devbox:ssh @bob/bob-box`).

## Prerequisites

- Access to the PostHog Tailscale tailnet (on macOS, the Tailscale app bundle CLI is detected automatically if `tailscale` isn't on PATH)
- Access to the internal Coder deployment at `https://coder.dev.posthog.dev`
- `hogli` available locally

## First-time setup

Run:

```bash
hogli devbox:setup
```

This does the host-side setup only:

- verifies Tailscale connectivity
- installs the `coder` CLI at the version matching the server
- logs you into the Coder deployment
- configures `~/.ssh/config` with Coder workspace entries (use `--skip-configure-ssh` to skip)
- prompts for Git identity, an optional dotfiles repo, and an optional Claude OAuth token (cached in macOS Keychain)

To reconfigure individual settings later, pass `--configure-git-identity`, `--configure-dotfiles`, or `--configure-claude`.

## Available commands

Run `hogli devbox` to see all available commands, and `hogli <command> --help` for options.

Runtime commands assume setup is already complete.
If they fail with `Run hogli devbox:setup`, rerun setup on your laptop first.

## Auth model

- Laptop to workspace access uses `coder ssh` and `coder config-ssh` (configured automatically during setup)
- Git inside the workspace should use HTTPS via Coder external auth — do not set up SSH Git inside the workspace
- Claude auth is passed through the `claude_oauth_token` Coder parameter, not AI Bridge. On macOS, the token is cached in Keychain.

`go/coder` is a convenient shortcut for humans, but the canonical deployment URL is `https://coder.dev.posthog.dev`.
