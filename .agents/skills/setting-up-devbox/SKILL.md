---
name: setting-up-devbox
description: Guide a PostHog engineer through spinning up, connecting to, and running commands on a remote devbox (a Coder workspace running the full PostHog stack). Use when asked to set up a devbox, start or connect to a devbox, configure remote dev, get gh CLI / Claude Code authed on a devbox, run a command on a devbox, or diagnose why a devbox command fails. Covers the tailnet prerequisite, hogli devbox commands, Coder user secrets for auth, and verifying with devbox:exec. How each dev personalizes their box is left to them.
---

# Setting up a PostHog devbox

A devbox is a Coder workspace running the full PostHog stack on an EC2 instance, managed through `hogli devbox:*` (the only supported interface — drive those commands, don't reimplement them). It ships ready to use: the repo cloned at `~/posthog`, the stack pre-warmed, and Claude Code installed. This skill gets a dev connected and working; how they personalize beyond that is their choice, not something to push.

## Prerequisite: tailnet access (the thing people miss)

The devbox control plane lives inside a private VPC reachable only over Tailscale. The ACL that grants the route is [`tailnet-policy.hujson`](https://github.com/PostHog/posthog-cloud-infra/blob/main/tailnet-policy.hujson) in `posthog-cloud-infra`: your email must be in **`group:engineering`**. Without that grant, the Coder control plane (`10.70.0.1:443`) is simply unroutable and _every_ `hogli devbox:*` command dies at the reachability check — not an auth or install problem, and no amount of re-running `devbox:setup` fixes it.

If `hogli devbox:doctor` reports the control plane unreachable, the fix is a PR adding the user to `group:engineering` in `tailnet-policy.hujson` (then ask Team DevEx if still blocked). Diagnose this before touching anything else.

## Workflow

### 1. Check state — `hogli devbox:doctor`

```bash
hogli devbox:doctor          # read-only: tailnet access, reachability, auth, ssh config, saved setup
```

A safe probe — it never prompts or mutates host config (unlike `devbox:setup`). If it flags the control plane unreachable, resolve the tailnet grant before anything else. For more detail: `hogli devbox:list` (your boxes), `hogli devbox:status` (state, template freshness), `hogli devbox:secret:list` (secret names only).

### 2. One-time local setup — `hogli devbox:setup`

Interactive: checks Tailscale + Coder reachability, installs and authenticates the `coder` CLI, and writes the SSH host entries that `devbox:ssh`/`devbox:exec` rely on. It then _offers_ git identity, git signing, a dotfiles repo, and your Claude token — all optional; `--skip-*` anything you don't want. Re-run one step with its flag, e.g. `hogli devbox:setup --configure-git-signing`.

### 3. Start and connect — `hogli devbox:start`

```bash
hogli devbox:start           # create or resume your box
hogli devbox:ssh             # shell in
hogli devbox:open --vscode   # or --cursor / --web
hogli devbox:stop            # when done — preserves disk, stops billing
```

### 4. Auth, if you want it (optional)

To have `gh` or Claude Code authenticated on the box, store the token once as a Coder user secret. It's injected as an env var into every box you start, so you set it once rather than per box:

```bash
hogli devbox:secret:set GH_TOKEN --env GH_TOKEN
hogli devbox:secret:set CLAUDE_CODE_OAUTH_TOKEN --env CLAUDE_CODE_OAUTH_TOKEN
# also supported: ANTHROPIC_API_KEY, OPENAI_API_KEY, OP_SERVICE_ACCOUNT_TOKEN, AWS_CREDENTIALS (--file)
```

Authing `gh` / Claude on a devbox is fine — that's what these are for. Set the value from `--file` or the hidden prompt; never paste a token into a command line or into this conversation. Restart a running box to pick up a newly set secret.

### 5. Make it yours — your call

The box is usable as shipped; personalize it however suits you, or not at all. Two supported paths, neither required, don't push one over the other:

- **Tweak the box directly** — `devbox:ssh` in and install tools, add aliases, clone repos. Changes under `/home` survive stop/start and template updates, but a `devbox:destroy` (or a brand-new box) starts fresh.
- **A dotfiles repo** — if you'd rather keep portable, version-controlled config that re-applies to every box: `hogli devbox:setup --configure-dotfiles` points the box at your `dotfiles_uri`, and Coder clones it (running an executable `~/dotfiles/install.sh` if present) on each start.

### 6. Run commands on the box — `hogli devbox:exec`

`devbox:exec` runs one command over SSH and propagates its exit code — handy for scripts, agents, and quick checks without opening a shell:

```bash
hogli devbox:exec -- bash -lc 'gh auth status'
hogli devbox:exec -- bash -lc 'cd ~/posthog && git status'
hogli devbox:exec -n api -- bash -lc 'uname -a'    # -n targets a labeled box
```

Wrap commands in `bash -lc '...'`: a non-login shell doesn't reliably source `~/.bashrc`/`~/.zshrc`, so a bare `gh auth status` can report "command not found" for anything on a login-shell `PATH` (e.g. `~/.local/bin`) — a false negative. The login shell also keeps the exit code trustworthy, so `&&` chaining and `if` checks work. Use `--` to separate hogli's flags from the command's own.

`devbox:exec` is not side-effect-free: like every `devbox:*` command it runs the reachability check first, which on Linux may `sudo tailscale set --accept-routes` and prompt for a password. Run `hogli devbox:setup` once interactively so routes and SSH config are in place before an agent drives `devbox:exec` unattended.

## Persistence & multiple boxes

- `devbox:stop` → `devbox:start` and template/AMI updates preserve `/home` (the instance is stopped, not terminated). A `devbox:destroy` wipes it — intentional, so don't keep anything irreplaceable only inside a box.
- You can run more than one box. Box-local changes don't carry between them; user secrets do (user-scoped), and a dotfiles repo does if you use one. That's the practical reason to reach for those if you find yourself re-doing setup — but it's a choice, not a requirement.

## Gotchas

- **Never echo secret values** into the transcript, logs, a PR, or a command line. `devbox:secret:set` reads from a hidden prompt or `--file`; `secret:list` shows names only. Keep it that way.
- **Secrets need a restart.** A new or changed secret only reaches boxes started afterward — `hogli devbox:restart` to pick it up on a running box.
- **`devbox:exec`/`devbox:ssh` need `devbox:setup` to have run** (it writes the `coder.*` SSH host config). Without it they fail at connection; `devbox:doctor` shows whether SSH access is configured.
- **`code-server` (browser IDE) has no SSH agent forwarding**, so commit signing via a forwarded key won't work there — use VS Code Desktop / Cursor / JetBrains (SSH-based) when you need to sign.
- **MCP OAuth on a devbox needs a port-forward, not a host rewrite.** The MCP server advertises `localhost:8010` as the OAuth authorization server. That's correct: the discovery endpoint must return JSON unauthenticated, which the Coder per-workspace subdomain can't do (its auth proxy 303s machine requests to an HTML login page). To let the laptop browser reach `/oauth/authorize`, run `hogli devbox:forward --port 8010` in a terminal during auth — same address the MCP worker on the devbox uses, so both legs agree. If you run Claude on the laptop instead of on the devbox, also forward 8787 in a second terminal (`hogli devbox:forward --port 8787`). Don't try to substitute the Coder subdomain — it breaks discovery.
