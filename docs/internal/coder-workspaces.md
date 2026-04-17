# Coder Workspaces

PostHog has an internal Coder deployment for cloud-hosted development workspaces.
Use this when you want a remote PostHog dev environment instead of running the full stack on your laptop.

## When to use it

- You want an isolated workspace for agentic or local development
- Your laptop does not have enough CPU, memory, or disk for local development
- You want a persistent remote workspace that is easy to stop and resume
- You are working from a machine where local Docker setup is inconvenient

## Prerequisites

- Access to the PostHog Tailscale tailnet (with subnet routes accepted)
- Access to the internal Coder deployment at `https://coder.dev.posthog.dev`
- `hogli` available locally

## First-time setup

Run:

```bash
hogli devbox:setup
```

This does the host-side setup only:

- verifies Tailscale connectivity and enables subnet route acceptance
- installs the Coder CLI into `~/.hogli/bin/` from the deployment's install script
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

## Sharing workspaces

You can share your devbox with other team members:

```bash
# List available Coder users
hogli devbox:users

# Share your workspace with another user
hogli devbox:share --user <username>

# Share with admin access (can start/stop the workspace)
hogli devbox:share --user <username> --role admin

# See who has access to your workspace
hogli devbox:share --list

# Revoke access
hogli devbox:unshare --user <username>
```

To access a workspace shared with you:

```bash
# Connect to another user's workspace
hogli devbox:ssh @username

# Connect to a specific labeled workspace
hogli devbox:ssh @username/label

# List workspaces (shows workspaces shared with you)
hogli devbox:list
```

The `@user` and `@user/label` syntax works across all `devbox:*` commands (ssh, open, forward, status, etc.).

After revoking access with `devbox:unshare`, restart the workspace for changes to take effect.

## Selecting workspaces

If you have multiple workspaces, specify which one to use:

```bash
# Use a labeled workspace
hogli devbox:ssh api

# Equivalent using --name flag
hogli devbox:ssh --name api
# or
hogli devbox:ssh -n api
```

When you have only one workspace, it is selected automatically.

## Auth model

- Laptop to workspace access uses `coder ssh` and optional `coder config-ssh`
- Git inside the workspace should use HTTPS via Coder external auth
- Do not set up SSH Git inside the workspace
- Claude auth for the workspace is passed through the `claude_oauth_token` Coder parameter, not AI Bridge

`go/coder` is a convenient shortcut for humans, but the canonical deployment URL is `https://coder.dev.posthog.dev`.
