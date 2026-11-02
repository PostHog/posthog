---
name: setting-up-devbox
description: Starts, connects to, and troubleshoots a PostHog devbox, a remote Coder workspace for PostHog development that can also run the full stack, through `hogli devbox:*` commands. Use when asked to spin up or resume a devbox, open a shell or editor on it, run a command on it, mirror a local checkout to it (devbox:sync), give each git worktree its own box (devbox:worktree), run the PostHog app on it and share a link, clone, update, share, or free disk on a devbox, store gh or Claude Code tokens for it, or diagnose a failing devbox command (tailnet, DNS, Coder CLI version, SSH). Not for running the stack on the local machine or for changing the Coder template in posthog-cloud-infra.
---

# Setting up a PostHog devbox

A devbox is a Coder workspace on EC2 for PostHog development.
Drive it through `hogli devbox:*` and don't reimplement what those commands do.
A new box has the repo at `~/posthog` on `master`, prewarmed dependencies, and Claude Code installed.
`hogli devbox:<command> --help` has the current flags.
This skill covers the order of operations and what the help text leaves out.

People use a box in different ways: a shell or editor for general development, a remote target for a local checkout, or a host for the running PostHog app.
Work out which one the user wants, and don't start the PostHog stack unless they ask for the app.

## Choosing an environment

When the user asks whether a devbox is the right place for the work, compare it with the other two options:

|                        | Local worktree                                                               | Devbox                                                                                                    | Tasks sandbox                                                                                                                                                                                                                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Persistence after stop | Everything stays on the user's machine.                                      | `devbox:stop` keeps the disk, including `/home`. Only `devbox:destroy` deletes it.                        | The sandbox is destroyed after an idle timeout: 30 minutes for background runs, 1 hour for user-created runs, 10 minutes for PostHog AI runs, and at most 2 hours with a per-task override. Interactive Modal runs snapshot `/tmp/workspace` before cleanup so a follow-up can restore it. Files outside `/tmp/workspace` are lost. |
| Context reset          | The user decides.                                                            | The user decides. Agent sessions on the box stay on its disk.                                             | Each task starts a new agent session. A follow-up on the same task resumes that session from the snapshot or the run log.                                                                                                                                                                                                           |
| Provisioning steps     | Create a worktree. Install dependencies or start the stack only when needed. | `devbox:doctor` and `devbox:setup` once per machine, then `devbox:start`.                                 | One message creates the task. The backend provisions the sandbox, clones the repository, and starts the agent.                                                                                                                                                                                                                      |
| MCP reach              | The MCP servers configured on the user's machine.                            | The MCP servers the user configures in Claude Code on the box.                                            | MCP Store installations: shared team installations, plus the user's personal installations for tasks they create. Built-in agent tasks get only the connections granted to that agent. PostHog Desktop can import or relay its own servers into a run.                                                                              |
| Preview URL            | `localhost:8010`                                                             | Stable and PostHog-internal: `https://app--<workspace>--<coder-user>.<coder-host>`.                       | One URL per run, `/api/projects/<team>/tasks/<task>/runs/<run>/preview/`, on the dev-stack image. It works only while the sandbox runs.                                                                                                                                                                                             |
| Cost                   | The user's machine.                                                          | An EC2 instance. Billing stops on `devbox:stop`.                                                          | Sandbox time is metered per run and counts against the team's PostHog Desktop usage limit.                                                                                                                                                                                                                                          |
| Best for               | Work that does not need the running stack.                                   | Long-lived state, MCP servers outside the MCP Store, a stable preview link, and agent history on the box. | Bounded one-off work that benefits from a fresh context.                                                                                                                                                                                                                                                                            |

A stopped box keeps its state, and `hogli devbox:start` (with `-n <label>` for a labeled box) resumes it.

## Get a box

Copy this checklist and track it:

```text
- [ ] 1. hogli devbox:doctor: the tailnet and control plane checks are ok
- [ ] 2. hogli devbox:setup has run on this machine
- [ ] 3. hogli devbox:start: the box is running
- [ ] 4. The user is connected the way they asked for
- [ ] 5. hogli devbox:stop when the user is done
```

### 1. Check access

`hogli devbox:doctor` is read-only: it never prompts or changes host config.
Commands that reach a box run the same reachability check first, so fix a failure here before anything else.

- The active tailnet must be `posthog.com`. Doctor prints it and names a wrong tailnet as the cause.
- Every PostHog employee has the route to the Coder control plane through `group:employees` in the tailnet policy. Nobody needs a PR to get access.
- If doctor reports the control plane unreachable, read [references/access-troubleshooting.md](references/access-troubleshooting.md) before changing anything.
- `[missing] Commit signing agent` does not block starting or using a box. It matters only for signed commits made on the box.

### 2. Set up this machine once

`hogli devbox:setup` is interactive, so ask the user to run it in their own terminal.
It installs the Coder CLI at the server's version into `~/.hogli/bin`, logs in, installs the pinned mutagen binary for `devbox:sync`, and writes the `coder.*` SSH host entries that `devbox:ssh` and `devbox:exec` use.
`~/.hogli/bin` is not on `PATH`, so call that CLI as `~/.hogli/bin/coder` when a step needs `coder` directly.
Each optional step has a `--configure-<step>` and `--skip-configure-<step>` flag: `ssh`, `git-identity`, `git-signing`, `region`, `dotfiles`, `claude`.
Run it again when a command prints `Coder CLI vX does not match server vY`, because it reinstalls the matching CLI.

On Linux, the reachability check can run `sudo tailscale set --accept-routes` and prompt for a password.
Run setup interactively once before an agent drives devbox commands unattended.

### 3. Start the box

```bash
hogli devbox:start
```

This creates the box on first use and resumes it after a stop.
It returns once the box's startup scripts finish, so the box is ready to connect to. `devbox:restart`, `devbox:update` and `devbox:clone` wait the same way. If a script fails or the wait gives up, the box still runs and hogli prints a warning that points to `hogli devbox:logs`.
It brings up the PostHog stack only when the workspace has `--start-app` set, which is covered in [Run the PostHog app](#run-the-posthog-app).
`--disk` (`100` or `200` GiB) applies only when the box is created.
When AWS has no capacity for the box's instance type in its zone (`InsufficientInstanceCapacity`), hogli starts the box on the template's other instance types by itself and keeps the disk. There is nothing to pass.
`--region` (`us-east-1` or `eu-central-1`) starts that region's default box and creates it if it doesn't exist, so leave it off when resuming an existing box.
A box's region can't change.

The default box is `devbox-<coder-user>`, and a labeled box is `devbox-<coder-user>-<label>`.
Boxes in `eu-central-1` add an `-eu` suffix, for example `devbox-<coder-user>-eu`.
`hogli devbox:list` shows the exact names.
Target a labeled box with `-n <label>` on commands that act on a box.

### 4. Connect

Match what the user asked for:

- **Shell:** `hogli devbox:ssh`.
- **Editor:** `hogli devbox:open --vscode`, `--cursor`, or `--web`.
- **Commands from an agent:** `hogli devbox:exec`, described in [Run commands on the box](#run-commands-on-the-box).
- **Edit locally, run on the box:** read [references/sync.md](references/sync.md) before using `hogli devbox:sync`.
- **The running app:** follow [Run the PostHog app](#run-the-posthog-app).
- **A box per git worktree:** follow [One devbox per worktree](#one-devbox-per-worktree).

### 5. Stop when done

`hogli devbox:stop` keeps the disk and stops billing.
It also pauses the box's `devbox:sync` mirror, and `devbox:start` resumes it.
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

- **New box:** `hogli devbox:start --start-app`. The setting stays on the workspace, so every later start brings the stack up in the background. The flag applies only when hogli creates the box; on an existing box hogli refuses it, because the Coder CLI keeps a parameter's last-build value. Change it on an existing box in the Coder dashboard under the workspace's parameters.
- **Running box:** `hogli devbox:exec -- bash -lc 'cd ~/posthog && ./bin/hogli up -d -y'`.

### Wait for it

The stack keeps booting after the start command returns.
Poll in a bounded loop until this prints `200` or `302`.
A `000` or `502` means the stack is still booting.

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
Coder runs the template's health check against the app, so read that status instead of sending a request with the user's session token:

```bash
~/.hogli/bin/coder list --output json | jq -r '.[] | select(.name=="<workspace>") | .latest_build.resources[]?.agents[]?.apps[]? | select(.slug=="app") | .health'
```

`healthy` means Coder routes the URL to a working app.
`initializing` means the check hasn't passed yet, and `unhealthy` means it keeps failing.

`hogli devbox:forward` is the alternative when the user wants `localhost`.
It tunnels box port 8010 to `localhost:8010` and holds the terminal until stopped.
Pass `--port 8011` when a local stack already uses 8010.

## One devbox per worktree

Use this when the user runs several local git worktrees and wants each one to run its stack on its own box.
Run `hogli devbox:worktree` from inside the linked worktree, never through `devbox:exec`.

```bash
hogli devbox:worktree --dry-run                 # print the box and sync plan
hogli devbox:worktree                           # start or create the box, then create the mirror
hogli devbox:worktree --clone-from default -y   # create the box as a clone of a running box
hogli devbox:worktree --on-clean stop           # save what worktrees:clean does with the box
```

- The label comes from the branch name, lowercased, with `/` and `_` turned into `-` and a leading `worktree-` dropped. Coder caps workspace names at 32 characters, so a long branch gets a shortened label with a 4-character hash. Pass `--label` to choose one.
- hogli records the worktree path and box name in `~/.config/posthog/hogli_devbox_worktrees.json`. A re-run reuses that box, even after a branch rename, and keeps an existing mirror.
- It refuses a derived label whose box already exists and is not recorded for this worktree, so it never takes over a box the user made by hand. Pass `--label <label>` to use that box on purpose. It always refuses a box recorded for another worktree.
- `--clone-from` uses `devbox:clone`, so the source must be running and the clone asks for confirmation unless `-y` is passed. Pass `-y` only after the user agrees.
- `hogli worktrees:clean --mode full --stop-boxes` stops the recorded box of each worktree it removes, and `--delete-boxes` deletes it with its disk. With neither flag, it uses the action saved by `--on-clean`, and `--keep-boxes` overrides that. It acts only on boxes in the record file, and skips a box that was recreated under the same name. A box it leaves alone is dropped from the record file, so a later run never touches it. `--dry-run` lists the boxes, and the confirmation prompt counts them.
- A box whose worktree was already removed gets the same action on the next `worktrees:clean` run, within that run's `--repo` and `--source` selection. A moved or unmounted worktree does not count as removed.
- Clear the saved action with `hogli devbox:config:rm worktree-boxes`.

### Provision a box for every new worktree

`hogli devbox:worktree --auto claude,phw` saves the worktree sources that get a box automatically.
The sources are `claude`, `codex`, `posthog-code`, `phw`, and `other` for a worktree outside those folders.
It only saves the setting, so run it from any checkout.
After that, the husky `post-checkout` hook runs `hogli devbox:worktree -y` in the background each time `git worktree add` creates a worktree from one of those sources.
That covers `claude -w`, Codex, PostHog Desktop, `phw`, and a plain `git worktree add`.

- Claude subagent worktrees (`.claude/worktrees/agent-*`) never get a box, so a fan-out of agents doesn't create one box per agent.
- The hook returns at once. Output goes to `hogli-devbox-worktree.log` in the worktree's git directory. Read it with `cat "$(git rev-parse --git-dir)/hogli-devbox-worktree.log"`.
- The hook skips the box when the main checkout has no Python environment to borrow, or when this worktree's `uv.lock` differs from the main checkout's.
- Turn it off with `hogli devbox:worktree --auto off` or `hogli devbox:config:rm worktree-auto`.
- Boxes keep running until `hogli worktrees:clean` removes their worktree, so pair this with `--on-clean stop`.

## Other tasks

- **Tokens on the box:** store them as Coder user secrets, which reach every box the user owns. `hogli devbox:secret:set GH_TOKEN` reads the value from a hidden prompt or from `--file`. Never put a token on a command line or in the conversation. A secret reaches only boxes started after it is set, so run `hogli devbox:restart` on a running box. The template documents `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `POSTHOG_GIT_SIGNING_KEY`, which `hogli devbox:setup --configure-git-signing` sets. `devbox:secret:list` shows names, env vars, and descriptions, never values.
- **A second box with the same state:** `hogli devbox:clone --as <label>` copies a running box's full disk, including any secrets on it, into `devbox-<coder-user>-<label>` in the source box's region. Stop the stack on the source first for a consistent copy. It asks for confirmation, so pass `-y` only after the user agrees. Only the owner can clone a box.
- **Template updates:** `hogli devbox:update` applies the latest template when the box is outdated. `devbox:start` also updates an outdated box when it starts it. Boxes that `devbox:start` and `devbox:clone` create have Coder's automatic updates on, so they also move to the latest template when they start from the web UI or autostart, and on `hogli devbox:restart`. Coder never updates a box while it keeps running, but a restart of an outdated box is a full template update and can trigger the one-time dependency re-install that `devbox:update` warns about.
- **Disk full:** `hogli devbox:cleanup:disk -n <label>` cleans a labeled box. With no workspace it cleans this machine instead, and the default box has no label, so clean the default box with `hogli devbox:exec -- bash -lc 'cd ~/posthog && ./bin/hogli devbox:cleanup:disk'`. `--docker` also prunes stopped containers, and `--cargo` also removes Rust build output, which forces a full rebuild.
- **Pairing:** `hogli devbox:share --user <coder-user> --role use` grants access, and `devbox:users` lists usernames. `devbox:unshare` removes access only after `hogli devbox:restart`.
- **Build and agent logs:** `hogli devbox:logs -f`.
- **Personal setup:** the box works as shipped. Changes made on the box survive stops and updates. `hogli devbox:setup --configure-dotfiles` saves a dotfiles repo that the box applies on start, running its executable `install.sh`. A saved repo URL applies to boxes hogli creates. To change it on an existing box, edit the workspace's parameters in the Coder dashboard.

## Gotchas

- Never echo a secret value into the transcript, logs, a PR, or a command line.
- `code-server` (`devbox:open --web`) has no SSH agent forwarding, so commit signing fails there. Use VS Code Desktop, Cursor, or JetBrains over SSH to sign commits.
