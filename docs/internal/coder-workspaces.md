# Coder Workspaces

PostHog has an internal Coder deployment for cloud-hosted development workspaces.
Use this when you want a remote PostHog dev environment instead of running the full stack on your laptop.

## When to use it

- You want an isolated workspace for agentic or local development
- Your laptop does not have enough CPU, memory, or disk for local development
- You want a persistent remote workspace that is easy to stop and resume
- You are working from a machine where local Docker setup is inconvenient

## Setting up with a coding agent

If you use a coding agent (Claude Code, Cursor, etc.), the `setting-up-devbox` skill teaches it this whole workflow — ask it to "set up my devbox" and it will check prerequisites, run setup, start a box, and verify access. It leans on two read/run helpers you can also use directly:

```bash
hogli devbox:doctor              # read-only health check: tailnet access, reachability, auth, ssh config
hogli devbox:exec -- bash -lc 'gh auth status'   # run one command on the box and get its exit code
```

`devbox:doctor` is the first thing to run when a devbox command misbehaves. It names the likely cause, most often the wrong tailnet, instead of failing cryptically.

## Common scenarios

**Connecting your IDE** —
Open the workspace in VS Code (`hogli devbox:open --vscode`), Cursor (`--cursor`), or a browser-based editor (`--web`).

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

**Editing locally while running on the devbox** —
Mirror your local PostHog checkout to a devbox with `hogli devbox:sync`. Local is the source of truth (one-way-safe); remote-only files like the AMI's prewarmed `node_modules` and `.venv` are left untouched. Useful for agentic loops or when you want to keep using your normal local editor without pushing every iteration:

```bash
hogli devbox:start                                   # ensure the box is running
hogli devbox:sync                                    # create the mirror (idempotent)
# edit files locally — changes propagate within seconds
hogli devbox:exec -- bash -lc 'cd ~/posthog && pnpm --filter=@posthog/frontend typescript:check'
hogli devbox:sync --status                           # check sync state
hogli devbox:sync --terminate                        # tear down when done
```

`devbox:open --vscode` / `--cursor` warns when sync is active, since editing over Remote-SSH while the mirror is live would conflict with the local source of truth.

**One devbox per git worktree** —
Run `hogli devbox:worktree` from a linked worktree to give it its own labeled box and sync mirror. The label comes from the branch name, shortened with a hash when it would push the workspace name past Coder's 32-character limit. Re-running reuses the same box and mirror. `--clone-from <label>` creates the box with `devbox:clone`, and `--dry-run` prints the plan.

`hogli worktrees:clean --mode full --stop-boxes` (or `--delete-boxes`) also stops (or deletes) the box of each worktree it removes. Save a default with `hogli devbox:worktree --on-clean stop|delete|keep`, and override it with `--keep-boxes`. Only boxes that `devbox:worktree` set up are touched.
It also handles boxes whose worktree was already removed some other way, but only once the box itself has not been used since the `--before` cutoff.

To give every new worktree a box, run `hogli devbox:worktree --auto claude,phw` once with the worktree sources you want (`claude`, `codex`, `posthog-code`, `phw`, `other`). The husky `post-checkout` hook then runs `devbox:worktree` in the background after `git worktree add`, including for `claude -w`. Claude subagent worktrees are skipped. Turn it off with `--auto off`.

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
- installs the `coder` CLI at the version matching the server and the `mutagen` binary (pinned v0.18.1) that powers `devbox:sync`
- logs you into the Coder deployment
- configures `~/.ssh/config` with Coder workspace entries (use `--skip-configure-ssh` to skip)
- shows a compact "Currently configured:" status block with your saved settings
- prompts for Git identity, an optional dotfiles repo, a preferred region, and an optional Claude OAuth token (stored as a Coder user secret)

A Y/n confirmation gate appears before the configuration prompts. It is automatically bypassed when stdin is non-TTY (scripts/CI) or when any explicit `--configure-*` or `--skip-configure-*` flag is passed.

To reconfigure individual settings later, pass `--configure-git-identity`, `--configure-dotfiles`, `--configure-region`, or `--configure-claude`. The `--configure-claude` flag manages the `CLAUDE_CODE_OAUTH_TOKEN` Coder user secret and will offer to migrate any existing macOS Keychain token.

## Managing devbox configuration

View your current devbox configuration:

```bash
hogli devbox:config:show
```

Clear specific saved settings with `devbox:config:rm`:

```bash
hogli devbox:config:rm git-identity   # clear saved Git name/email
hogli devbox:config:rm git-signing    # remove Git signing key from Coder user secrets
hogli devbox:config:rm dotfiles       # clear dotfiles URI for new workspaces
hogli devbox:config:rm claude         # remove Claude OAuth token from Coder user secrets
hogli devbox:config:rm region          # clear saved region preference (new workspaces use the built-in default)
hogli devbox:config:rm --all          # clear everything
```

Saved settings apply to workspaces hogli creates.
The Coder CLI keeps a parameter's last-build value even when hogli passes a new one, so to change a setting on an existing workspace, edit its parameters in the Coder dashboard.

## Available commands

Run `hogli devbox` to see all available commands, and `hogli <command> --help` for options.

Region selection is available for `devbox:start` via `--region` (`us-east-1` or `eu-central-1`, default `us-east-1`). The region is set once at creation and cannot be changed. Workspaces in `eu-central-1` get an `-eu` name suffix (e.g. `devbox-alice-eu`). `devbox:list` and `devbox:status` show which region a workspace is in.

`devbox:start --start-app` opts a workspace into bringing the PostHog app up (`hogli up`) in the background on every start — useful for scripted, ephemeral devboxes that should be usable without an interactive `hogli up`. The setting is stored as a workspace parameter (`auto_start_app`), so it stays in effect for future starts. The flag applies only when hogli creates the devbox; on an existing devbox hogli refuses it, and the parameter can be changed in the Coder dashboard. Requires a template version that defines the parameter; on older templates hogli drops it with a warning.

When a build fails with `InsufficientInstanceCapacity`, AWS has no free capacity for the box's instance type in its availability zone.
`devbox:start`, `devbox:restart` and `devbox:update` then start the box on the template's other instance types in turn, through the Coder build API, because the Coder CLI keeps a parameter's last-build value.
The template changes the type of the same instance, so the disk stays, and the box keeps the type that started.

Runtime commands assume setup is already complete.
If they fail with `Run hogli devbox:setup`, rerun setup on your laptop first.
When in doubt, `hogli devbox:doctor` reports which prerequisite is missing.

## Managing Coder user secrets

hogli provides commands to manage Coder user secrets (requires Coder 2.33+):

```bash
hogli devbox:secret:list                           # list all user secrets
hogli devbox:secret:set NAME --description "..."   # create or replace a secret
hogli devbox:secret:set NAME --file PATH           # set secret value from file
hogli devbox:secret:rm NAME                        # delete a secret
```

Common secrets include `CLAUDE_CODE_OAUTH_TOKEN` and `GH_TOKEN`.

## Auth model

- Laptop to workspace access uses `coder ssh` and `coder config-ssh` (configured automatically during setup)
- Git inside the workspace should use HTTPS via Coder external auth — do not set up SSH Git inside the workspace
- Claude auth is stored as a Coder user secret named `CLAUDE_CODE_OAUTH_TOKEN` (requires Coder 2.33+). Run `hogli devbox:setup --configure-claude` to set or replace it.

`go/coder` is a convenient shortcut for humans, but the canonical deployment URL is `https://coder.dev.posthog.dev`.
