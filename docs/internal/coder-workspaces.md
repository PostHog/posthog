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

Project tools such as `pnpm` and `pytest` are on `PATH` only inside PostHog's flox environment.
Add `--flox` to run the command in `~/posthog` inside it, for example `hogli devbox:exec --flox -- pnpm --filter=@posthog/frontend typescript:check`.

`devbox:doctor` is the first thing to run when a devbox command misbehaves. It names the likely cause, most often the wrong tailnet, instead of failing cryptically.

## Common scenarios

**Connecting your IDE** —
Open the workspace in VS Code (`hogli devbox:open --vscode`), Cursor (`--cursor`), or a browser-based editor (`--web`).

**Driving a devbox from Herdr** —
`hogli devbox:open --herdr` adds the devbox to [Herdr](https://herdr.dev) as a machine and opens a space on it in `~/posthog`.
Terminals and agents you open in that space run on the devbox.
The first run copies `hc` onto the box; later runs show the same space again.
The devbox must be running, so run `hogli devbox:start` first.
Stopping the devbox ends its terminals, and Herdr gives each pane a new shell after the next start.
Deleting a devbox with `hogli devbox:destroy` or a worktree cleanup command also removes its Herdr machine.

Herdr users pick one of two ways to work:

- **Agents on the devbox.** Run `hogli devbox:open --herdr` and create worktrees from that space. They live on the devbox, and nothing syncs. The worktrees share one devbox, so only one of them runs the dev stack at a time.
- **Agents on your laptop.** Run `hogli devbox:worktree --auto herdr`. Each worktree that Herdr creates on your laptop gets its own devbox, with its own dev stack. The mirror copies your edits to the box, so edit locally. `hogli devbox:open --herdr <label>` opens a space on a worktree's box to run the stack and tests there.

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
A teammate you share with gets a shell on the box as you, so they can also use your Claude Code login there.
When the box is logged in, `devbox:share` offers to log out of Claude Code first. It refuses to share when it can't check the login, for example on a stopped box or without a terminal to ask in. Pass `--keep-claude-login` to share with the login on the box.

**Editing locally while running on the devbox** —
Mirror your local PostHog checkout to a devbox with `hogli devbox:sync`. Local is the source of truth (one-way-safe); remote-only files like the AMI's prewarmed `node_modules` and `.venv` are left untouched. Useful for agentic loops or when you want to keep using your normal local editor without pushing every iteration:

```bash
hogli devbox:start                                   # ensure the box is running
hogli devbox:sync                                    # create the mirror (idempotent)
# edit files locally — changes propagate within seconds
hogli devbox:exec --flox -- pnpm --filter=@posthog/frontend typescript:check
hogli devbox:sync --status                           # check sync state
hogli devbox:sync --terminate                        # tear down when done
```

`devbox:open --vscode` / `--cursor` / `--herdr` warns when sync is active, since editing over Remote-SSH while the mirror is live would conflict with the local source of truth. For a worktree's devbox, the warning names the worktree to edit instead.

The mirror leaves out `.git`, so `git rev-parse HEAD` on the box names the box's own checkout, not your local commit.
To make `/_livez`, the debug badge and the `X-PostHog-Build` header show your commit, start the app with `POSTHOG_GIT_COMMIT` set to the full 40-character lowercase SHA from your local `git rev-parse HEAD`.
A `commit.txt` in the checkout takes precedence over the variable, and an empty or malformed value falls back to git.

**One devbox per git worktree** —
Run `hogli devbox:worktree` from a linked worktree to give it its own labeled box and sync mirror. The label comes from the branch name without a leading `<coder-user>/`, shortened with a hash when it would push the workspace name past Coder's 32-character limit. Re-running reuses the same box and mirror. Inside that worktree, commands such as `devbox:exec`, `devbox:ssh` and `devbox:status` target its box without `-n <label>` and print which box they picked, and `-n @<coder-user>` targets your default box. When that box was deleted, they stop and point to `hogli devbox:worktree` to create it again. `--clone-from <label>` creates the box with `devbox:clone`, and `--dry-run` prints the plan.

`hogli worktrees:clean --mode full --stop-boxes` (or `--delete-boxes`) also stops (or deletes) the box of each worktree it removes. Save a default with `hogli devbox:worktree --on-clean stop|delete|keep`, and override it with `--keep-boxes`. Only boxes that `devbox:worktree` set up are touched.
It also handles boxes whose worktree was already removed some other way, but only once the box itself has not been used since the `--before` cutoff.
`hogli devbox:worktree:prune` handles only those boxes, with no cutoff, after t3code, herdr or `git worktree remove` deleted the worktree.

To give every new worktree a box, run `hogli devbox:worktree --auto claude,phw` once with the worktree sources you want (`claude`, `codex`, `posthog-code`, `phw`, `t3code`, `herdr`, `superset`, `emdash`, `orca`, `conductor`, `worktrunk`, `paseo`, `other`). The husky `post-checkout` hook then runs `devbox:worktree` in the background after `git worktree add`, including for `claude -w`. Superset, Emdash, Orca and worktrunk run it from the create hooks checked into the repo, and stop the box from their remove hooks. For Conductor, `--auto conductor` adds the same hooks to your uncommitted `.conductor/settings.local.toml`, so other people's Conductor scripts stay as they are. t3code runs it only after you import `t3.json` once with **Import from t3.json** in the project's scripts. herdr users link `tools/herdr-devbox-plugin` with `herdr plugin link`. Paseo users add the same hooks to an untracked `paseo.json` in the main checkout, which Paseo copies into each new worktree. Claude subagent worktrees are skipped. Turn it off with `--auto off`.

**Worktree boxes on Hogland** —
`hogli devbox:worktree --provider hogland` gives the worktree a Hogland devbox instead of a Coder workspace.
It restores the box from the `devbox-golden` snapshot with `hogland devbox up`, so the `hogland` CLI must be installed and signed in.
The box is named `wt-<label>` and the mirror goes to `/home/hog/posthog` over SSH.
To make Hogland the default, including for automatic boxes, pass `--provider hogland` together with `--auto`.
`hogli devbox:config:rm worktree-provider` goes back to Coder.
`worktrees:clean --stop-boxes` hibernates a Hogland box, and `--delete-boxes` deletes it.
`--clone-from <label>` clones the running Hogland devbox `wt-<label>` with `hogland devbox clone`, which needs a recent `hogland` CLI.
`--start-app` on a new box saves the file `~/.config/hogli/start-app` on it, and every later `devbox:worktree` run then starts the app with `hogli up -d`.

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
- links `coder` into `~/.local/bin` (or `~/bin`) when that directory is on your PATH, so you can run `coder` yourself; otherwise it prints the PATH line to add
- logs you into the Coder deployment. Login asks you to paste a token from the browser, so run setup in a terminal that takes input. In a shell without one, setup stops and tells you to run `coder login` in a terminal first
  - Without a terminal, set `CODER_SESSION_TOKEN` to a token from `https://coder.dev.posthog.dev/cli-auth` and `CODER_URL` to `https://coder.dev.posthog.dev`. The Coder CLI uses that token before any stored login, so login and every `hogli devbox:*` command work with no `coder login`. Setup still prompts for each configuration step you have not saved, so pass its `--skip-configure-*` flag. If login with the token fails, hogli shows the Coder error instead of asking you to log in
  - The Coder SSH entries read the login stored on disk, so a program that doesn't inherit `CODER_SESSION_TOKEN`, such as an editor or a mutagen daemon started from another shell, can't connect. When only the variable holds the login, setup prints the command that stores it: `coder login --use-token-as-session <url>`. Store it again after the token changes
- configures `~/.ssh/config` with Coder workspace entries (use `--skip-configure-ssh` to skip)
- shows a compact "Currently configured:" status block with your saved settings
- prompts for Git identity, an optional dotfiles repo, a preferred region, and how devboxes use Claude Code (see [Claude Code on a devbox](#claude-code-on-a-devbox))

A Y/n confirmation gate appears before the configuration prompts. It is automatically bypassed when stdin is non-TTY (scripts/CI) or when any explicit `--configure-*` or `--skip-configure-*` flag is passed.

To reconfigure individual settings later, pass `--configure-git-identity`, `--configure-dotfiles`, `--configure-region`, or `--configure-claude`.

When your global git config signs with a Secure Enclave key (`hogli git:signing-key`), the forwarded SSH agent can't sign with it on a devbox.
Setup then looks for a key that your forwarded agent holds and that GitHub lists as one of your signing keys, and offers to use it for devbox commits.
That key isn't in the Secure Enclave, so use it only until devboxes support Secure Enclave signing.

## Claude Code on a devbox

Every devbox has Claude Code installed. Log in on the box itself:

```bash
hogli devbox:claude:login     # run `claude auth login` on the box; run it again to switch accounts
hogli devbox:claude:status    # show the account, auth method and plan, never a credential
hogli devbox:claude:logout    # run `claude auth logout` on the box
```

Add `-n <label>` to target a labeled box.
The login stays in `~/.claude/.credentials.json` on the box, so it survives stops, starts and updates, and each box has its own login.
`devbox:claude:logout` deletes the login from the box.
`devbox:destroy` logs out of Claude Code on a running box before it deletes the box and its disk.
When you leave, run `devbox:claude:logout` on each box that has a login.
Logout only deletes the box's copy of the login. If the login may have been copied off the box, for example after a compromise, also end it on the Claude side: sign out of your sessions in your claude.ai account settings, or ask an admin of your Claude organization to revoke it.

`devbox:setup` asks how devboxes use Claude Code:

- **login** (default): log in on each box with `devbox:claude:login` after it starts. hogli stores nothing.
- **token**: store a token from `claude setup-token` as the `CLAUDE_CODE_OAUTH_TOKEN` Coder user secret, for unattended use. The token can only make model requests, so Remote Control and usage checks don't work with it. Every box you own gets it, and it overrides a login on the box.
- **skip**: choose later with `hogli devbox:setup --configure-claude`.

`devbox:claude:login` offers to delete the token secret when it exists. Restart a running box after you delete it, so the box drops the token from its environment.

hogli never turns on Remote Control. It gives another way into the box, so turn it on only when you need it, and don't combine it with skipped permission prompts.
To use it after `devbox:claude:login`, run `claude rc` in a terminal on the box that stays open, such as a Herdr tab, and start sessions from claude.ai/code or the Claude app. `/rc` connects one running session. See [Remote Control](https://code.claude.com/docs/en/remote-control).

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
hogli devbox:config:rm claude         # remove the Claude setup token from Coder user secrets
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

After your own box starts, `devbox:start` lists the per-box setup it still needs, such as the Claude Code, GitHub CLI and Trunk CLI logins or dotfiles that failed to clone, with the command that sets each one up.
Run `hogli devbox:check` to see the same list at any time.

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

## Lending 1Password secrets to a box

For keys a box needs only for a while, such as `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` for evals, lend them from 1Password instead of storing Coder user secrets.
List the 1Password references, never the values, in `~/.config/posthog/devbox-secrets.env` on your laptop:

```bash
OPENAI_API_KEY=op://<vault>/<item>/<field>
ANTHROPIC_API_KEY=op://<vault>/<item>/<field>
```

```bash
hogli devbox:secrets:push      # one 1Password unlock; the box keeps them for 12h (--hours to change)
hogli devbox:secrets:status    # names and time left, never values
hogli devbox:secrets:clear     # remove them now
```

The box keeps them in memory only (`/dev/shm`, readable by your user alone), so they go when the box stops, and the box deletes them when the time runs out.
They are not in the environment. On the box, run a command that needs them with `devbox-secrets run -- <command>`, the way `op run` works locally.
The push adds a note to the box's `~/.claude/CLAUDE.md` so agents there know to do the same.
Anything running as you on the box can read them while they're lent, so lend keys with spending limits.
Push refuses a box that is shared with any user or group, and `devbox:share` refuses while secrets are lent.
A command that `devbox-secrets run` started keeps the values after they expire or you clear them, so `devbox:share` also refuses while one runs.
Unsharing doesn't end a former sharee's shells or processes. Restart the box after `devbox:unshare` and before you lend to it.
Values must fit on one line. Push refuses a 1Password field with line breaks, such as a certificate.

## GitHub on a devbox

By default, git on a box uses Coder's GitHub app. It reaches only the repositories where a GitHub org admin installed that app, and only in SSH sessions, which get it through `GIT_ASKPASS`. `gh` doesn't use it.

To use `gh`, log it in on the box:

```bash
hogli devbox:gh:login     # gh prints a code to enter at https://github.com/login/device
hogli devbox:gh:status    # account and scopes, token masked
hogli devbox:gh:logout    # delete the login from the box
```

Login also runs `gh auth setup-git`, so git uses the same login. git and `gh` then reach every repository your GitHub account can, in every process on the box, including Herdr tabs and agents that outlive the SSH connection that started them.
Login also installs the `gh stack` extension when it's missing, for [stacked PRs](https://github.com/github/gh-stack).
A private dotfiles repo fails to clone when a box first starts, because only Coder's app can reach GitHub then. Login applies your dotfiles again when that happened, and `hogli devbox:dotfiles` does the same on demand.
After a logout, git falls back to Coder's app.

The token stays on the box's disk until you log out or destroy the box. People you share the box with can read it, so `devbox:share` offers to log out first.
Logging out deletes only the box's copy. To revoke the token, remove GitHub CLI under Settings > Applications on github.com, which also logs `gh` out on your other computers.
A `GH_TOKEN` Coder user secret takes priority over the login for `gh`.

To use the merge queue with `trunk merge` from the box, log the Trunk CLI in the same way:

```bash
hogli devbox:trunk:login     # trunk prints a link to open on your computer
hogli devbox:trunk:status    # the Trunk account the box uses
hogli devbox:trunk:logout    # delete the login from the box
```

The Trunk CLI comes from PostHog's flox environment in `~/posthog`. If login can't find it, run `hogli devbox:exec --flox -- true` once to set up the environment.
The Trunk login also stays on the box's disk, and people you share the box with could use it to put PRs in the merge queue as you. `devbox:share` offers to log out first, like it does for `gh`.

## Auth model

- Laptop to workspace access uses `coder ssh` and `coder config-ssh` (configured automatically during setup)
- SSH to a stopped devbox fails with "workspace must be started" instead of starting it. Run `hogli devbox:start` first. Tools that reconnect in the background, such as Herdr and editors, would otherwise queue a new build on every retry.
- Git inside the workspace uses HTTPS, through Coder external auth or `hogli devbox:gh:login`. Don't set up SSH Git inside the workspace. See [GitHub on a devbox](#github-on-a-devbox).
- Claude Code logs in on each box with `hogli devbox:claude:login`. The optional `CLAUDE_CODE_OAUTH_TOKEN` Coder user secret (requires Coder 2.33+) overrides that login on every box. See [Claude Code on a devbox](#claude-code-on-a-devbox).

`go/coder` is a convenient shortcut for humans, but the canonical deployment URL is `https://coder.dev.posthog.dev`.
