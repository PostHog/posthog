---
name: setting-up-devbox
description: Starts, connects to, and troubleshoots a PostHog devbox, a remote Coder workspace for PostHog development that can also run the full stack, through `hogli devbox:*` commands. Use when asked to spin up or resume a devbox, open a shell or editor on it, run a command on it, mirror a local checkout to it (devbox:sync), run the PostHog app on it and share a link, clone, update, share, or free disk on a devbox, store gh or Claude Code tokens for it, or diagnose a failing devbox command (tailnet, DNS, Coder CLI version, SSH). Not for running the stack on the local machine or for changing the Coder template in posthog-cloud-infra.
---

# Setting up a PostHog devbox

A devbox is a Coder workspace on EC2 for PostHog development.
Drive it through `hogli devbox:*` and don't reimplement what those commands do.
A new box has the repo at `~/posthog` on `master`, prewarmed dependencies, and Claude Code installed.
`hogli devbox:<command> --help` has the current flags.
This skill covers the order of operations and what the help text leaves out.

People use a box in different ways: a shell or editor for general development, a remote target for a local checkout, or a host for the running PostHog app.
Work out which one the user wants, and don't start the PostHog stack unless they ask for the app.

## Get a box

Copy this checklist and track it:

```text
- [ ] 1. hogli devbox:doctor: every access check is ok
- [ ] 2. hogli devbox:setup has run on this machine
- [ ] 3. hogli devbox:start: the box is running
- [ ] 4. The user is connected the way they asked for
- [ ] 5. hogli devbox:stop when the user is done
```

### 1. Check access

`hogli devbox:doctor` is read-only: it never prompts or changes host config.
Every other devbox command runs the same reachability check first, so fix a failure here before anything else.

- The active tailnet must be `posthog.com`. Doctor prints it and names a wrong tailnet as the cause.
- Every PostHog employee has the route to the Coder control plane through `group:employees` in the tailnet policy. Nobody needs a PR to get access.
- If doctor reports the control plane unreachable, read [references/access-troubleshooting.md](references/access-troubleshooting.md) before changing anything.
- `[missing] Commit signing agent` does not block starting or using a box. It matters only for signed commits made on the box.

### 2. Set up this machine once

`hogli devbox:setup` is interactive, so ask the user to run it in their own terminal.
It installs the Coder CLI at the server's version into `~/.hogli/bin`, logs in, installs the pinned mutagen binary for `devbox:sync`, and writes the `coder.*` SSH host entries that `devbox:ssh` and `devbox:exec` use.
Each optional step has a `--configure-<step>` and `--skip-configure-<step>` flag: `ssh`, `git-identity`, `git-signing`, `region`, `dotfiles`, `claude`.
Run it again when a command prints `Coder CLI vX does not match server vY`, because it reinstalls the matching CLI.

On Linux, the reachability check can run `sudo tailscale set --accept-routes` and prompt for a password.
Run setup interactively once before an agent drives devbox commands unattended.

### 3. Start the box

```bash
hogli devbox:start
```

This creates the box on first use and resumes it after a stop.
It brings up the PostHog stack only when the workspace has `--start-app` set, which is covered in [Run the PostHog app](#run-the-posthog-app).
`--region` (`us-east-1` or `eu-central-1`) and `--disk` (`100` or `200` GiB) apply only when the box is created, and a box's region can't change.
The default box is `devbox-<coder-user>`.
A labeled box is `devbox-<coder-user>-<label>`; target it with `-n <label>` on any command.

### 4. Connect

Match what the user asked for:

- **Shell:** `hogli devbox:ssh`.
- **Editor:** `hogli devbox:open --vscode`, `--cursor`, or `--web`.
- **Commands from an agent:** `hogli devbox:exec`, described in [Run commands on the box](#run-commands-on-the-box).
- **Edit locally, run on the box:** read [references/sync.md](references/sync.md) before using `hogli devbox:sync`.
- **The running app:** follow [Run the PostHog app](#run-the-posthog-app).

### 5. Stop when done

`hogli devbox:stop` keeps the disk and stops billing.
Stops, starts, and `devbox:update` keep `/home`.
`hogli devbox:destroy` deletes it, so don't keep anything irreplaceable only on a box.

## Run commands on the box

`hogli devbox:exec -- <command>` runs one command over SSH and returns its exit code.
Wrap the command in `bash -lc '...'`.
A non-login shell doesn't reliably load the shell profile, so tools on a login-shell `PATH` such as `~/.local/bin` report "command not found".
Put `--` between hogli's flags and the command's own.
`devbox:exec` and `devbox:ssh` fail to connect until `devbox:setup` has written the SSH config.

## Run the PostHog app

Use this section only when the user wants the app, for example to QA a change or share a link.

### Start the stack

- **New or stopped box:** `hogli devbox:start --start-app`. The flag stays set on the workspace, so every later start brings the stack up in the background until `hogli devbox:start --no-start-app` turns it off.
- **Running box:** `hogli devbox:exec -- bash -lc 'cd ~/posthog && ./bin/hogli up -d -y'`.

### Wait for it

The stack keeps booting after the start command returns.
Poll in a bounded loop until this prints `200` or `302`.
A `502` means the stack is still booting.

```bash
hogli devbox:exec -- bash -lc "curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8010/"
```

When resuming QA on an existing box, check it before recreating sync, restarting the stack, or making a new box:

```bash
hogli devbox:status
hogli devbox:exec -- bash -lc 'cd ~/posthog && git status --short --branch && git rev-parse --short HEAD'
hogli devbox:sync --json
```

Keep going when the app serves the intended branch and SHA, the target route loads, and its APIs work.
Note unrelated degraded processes instead of chasing full health.

### Give the user the URL

The template exposes the app as a Coder subdomain app that only the box owner can open:

```text
https://app--<workspace>--<coder-user>.<coder-host>
```

`<coder-host>` is the host of `Coder URL` in `hogli devbox:doctor`, and `hogli devbox:list` shows the workspace name.
For example, `devbox-jane-d` owned by `jane-d` on `coder.dev.posthog.dev` is `https://app--devbox-jane-d--jane-d.coder.dev.posthog.dev`.
The user must be on the tailnet, and the browser goes through Coder sign-in first.

Verify the link before handing it over.
This passes the session token to curl on stdin, so it stays out of the output and out of the process list:

```bash
coder login token | sed 's/^/Coder-Session-Token: /' | curl -s -o /dev/null -w '%{http_code}' -H @- "https://app--<workspace>--<coder-user>.<coder-host>/_health/"
```

A `200` means Coder routes to a healthy app.

`hogli devbox:forward` is the alternative when the user wants `localhost`.
It tunnels box port 8010 to `localhost:8010` and holds the terminal until stopped.
Pass `--port 8011` when a local stack already uses 8010.

## Other tasks

- **Tokens on the box:** store them as Coder user secrets, which reach every box the user owns. `hogli devbox:secret:set GH_TOKEN` reads the value from a hidden prompt or from `--file`. Never put a token on a command line or in the conversation. A secret reaches only boxes started after it is set, so run `hogli devbox:restart` on a running box. The template documents `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, `OP_SERVICE_ACCOUNT_TOKEN`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY`. `devbox:secret:list` shows names only.
- **A second box with the same state:** `hogli devbox:clone --as <label>` copies a running box's full disk into `devbox-<coder-user>-<label>`. Only the owner can clone a box.
- **Template updates:** `hogli devbox:update` applies the latest template when the box is outdated.
- **Disk full:** `hogli devbox:cleanup:disk`. `--docker` also prunes stopped containers, and `--cargo` also removes Rust build output, which forces a full rebuild.
- **Pairing:** `hogli devbox:share --user <coder-user> --role use` grants access, `devbox:users` lists usernames, and `devbox:unshare` revokes access.
- **Build and agent logs:** `hogli devbox:logs -f`.
- **Personal setup:** the box works as shipped. Changes made on the box survive stops and updates. `hogli devbox:setup --configure-dotfiles` applies a dotfiles repo on every start and runs its executable `install.sh`. Neither is required, so don't push one over the other.

## Gotchas

- Don't use `hogli devbox:task`. The Coder deployment no longer runs Coder Tasks. Start a normal box and drive the agent over `devbox:exec` instead.
- Never echo a secret value into the transcript, logs, a PR, or a command line.
- `code-server` (`devbox:open --web`) has no SSH agent forwarding, so commit signing fails there. Use VS Code Desktop, Cursor, or JetBrains over SSH to sign commits.
