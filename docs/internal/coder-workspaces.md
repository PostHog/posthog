# Coder Workspaces

PostHog has an internal Coder deployment for cloud-hosted development workspaces.
Use this when you want a remote PostHog dev environment instead of running the full stack on your laptop.

## When to use it

- You want an isolated workspace for agentic or local development
- Your laptop does not have enough CPU, memory, or disk for local development
- You want a persistent remote workspace that is easy to stop and resume
- You are working from a machine where local Docker setup is inconvenient

## Prerequisites

- Access to the PostHog Tailscale tailnet
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
- optionally runs `coder config-ssh` for local SSH/editor access

## Available commands

Run:

```bash
hogli devbox
```

Then use `hogli <command> --help` for command-specific options.
If your template includes the Claude module, `hogli devbox:start` can prompt for a Claude OAuth token when the workspace is created.
After connecting with `hogli devbox:ssh`, run `claude` directly in the workspace terminal.

Runtime commands assume setup is already complete.
If they fail with `Run hogli devbox:setup`, rerun setup on your laptop first.

## Auth model

- Laptop to workspace access uses `coder ssh` and optional `coder config-ssh`
- Git inside the workspace should use HTTPS via Coder external auth
- Do not set up SSH Git inside the workspace
- Claude auth for the workspace is passed through the `claude_oauth_token` Coder parameter, not AI Bridge

`go/coder` is a convenient shortcut for humans, but the canonical deployment URL is `https://coder.hedgehog-kitefin.ts.net`.
