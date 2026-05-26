---
name: setting-up-devbox
description: Set up and personalize a PostHog remote devbox (Coder workspace) so the same config lands on every box you own, not just one. Use when asked to set up a devbox, personalize a devbox, configure remote dev, get gh CLI / Claude Code / PostHog MCP / aliases working on a devbox, write devbox dotfiles, or make a new devbox match an existing one. Covers hogli devbox commands, Coder user secrets, dotfiles, and verifying setup with devbox:exec.
---

# Setting up a PostHog devbox

A devbox is a Coder workspace running the full PostHog stack on an EC2 instance. `hogli devbox:*` is the only supported interface — this skill drives those commands, it does not reimplement them.

## Prerequisite: tailnet access (the thing people miss)

The devbox control plane lives inside a private VPC reachable only over Tailscale. The ACL that grants the route is [`tailnet-policy.hujson`](https://github.com/PostHog/posthog-cloud-infra/blob/main/tailnet-policy.hujson) in `posthog-cloud-infra`: your email must be in **`group:engineering`**. Without that grant, the Coder control plane (`10.70.0.1:443`) is simply unroutable and _every_ `hogli devbox:*` command dies at the reachability check — not an auth or install problem, and no amount of re-running `devbox:setup` fixes it.

If `hogli devbox:doctor` reports the control plane unreachable, the fix is a PR adding the user to `group:engineering` in `tailnet-policy.hujson` (then ask Team DevEx if still blocked). Diagnose this before touching anything else.

## The one rule: personalize the human, not the box

People run **more than one devbox**, and a box's compute is rebuilt from a golden image. So anything you hand-install inside a single box is a pet — it does not follow you to box #2, and a rebuild can wipe it. Setup is "done" only when it is **portable**: it re-applies automatically to every box you create. Two mechanisms give you that, and almost everything belongs in one of them:

| Mechanism                        | Scope           | Fans out to all boxes?                    | Holds                                                                           |
| -------------------------------- | --------------- | ----------------------------------------- | ------------------------------------------------------------------------------- |
| **Dotfiles repo** (`install.sh`) | your git repo   | yes — cloned + run on every box start     | tools, aliases, MCP registration, `gh` install, shell config, skills/extensions |
| **Coder user secrets**           | your Coder user | yes — injected as env vars into every box | `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, API keys, signing key                    |

If you find yourself `ssh`-ing in to install something, stop — that change belongs in the dotfiles `install.sh` so it replays. Use `devbox:exec` to _verify_ and to _prototype_, then move what worked into `install.sh`.

## Workflow

### 1. Read current state first — don't ask what you can detect

```bash
hogli devbox:doctor          # read-only: tailnet access, reachability, auth, saved setup
```

`devbox:doctor` is the safe probe — it never prompts or mutates host config (unlike `devbox:setup`). It confirms the tailnet prerequisite above, then reports git identity, dotfiles URI, and which user secrets are set. If it flags the control plane unreachable, resolve the tailnet grant before anything else. For more detail: `hogli devbox:list` (boxes), `hogli devbox:status` (state/template freshness), `hogli devbox:secret:list` (secret names only).

### 2. Local access + identity (once per machine)

```bash
hogli devbox:setup
```

Interactive; checks Tailscale + Coder reachability, installs/auths the `coder` CLI, then walks: SSH host entries, git name/email, git signing key, dotfiles URI, Claude token. Non-interactive flags exist for each: `--configure-ssh`, `--configure-git-identity`, `--configure-git-signing`, `--configure-dotfiles`, `--configure-claude` (each has a `--skip-*` form). Run targeted re-config with a single flag, e.g. `hogli devbox:setup --configure-dotfiles`.

### 3. Portable identity — the part that fans out

**Secrets** (user-scoped, land in every box as env vars; restart a running box to pick up changes):

```bash
hogli devbox:secret:set GH_TOKEN --env GH_TOKEN        # gh CLI + git over HTTPS; prompts hidden
hogli devbox:secret:set CLAUDE_CODE_OAUTH_TOKEN --env CLAUDE_CODE_OAUTH_TOKEN
# also supported: ANTHROPIC_API_KEY, OPENAI_API_KEY, OP_SERVICE_ACCOUNT_TOKEN, AWS_CREDENTIALS (--file)
```

Yes, authing `gh` / Claude on a devbox is fine — that is what these secrets are for. Set the value from a file or the hidden prompt; never paste a token into a command line or into this conversation.

**Dotfiles** are where agentic tooling and shell config live. The Coder dotfiles module clones your `dotfiles_uri` into `~` on every box and runs an executable `~/dotfiles/install.sh` if present (otherwise it symlinks dotfiles). This is the portable home for everything people otherwise hand-roll per box: install `gh`, register the PostHog MCP server, write Claude `settings.json`, add aliases, clone extra repos, sync skills/`pi` extensions.

If the user has no dotfiles repo, offer to scaffold a minimal one with an `install.sh` doing their setup (it must be `chmod +x` and committed). Point the box at it:

```bash
hogli devbox:setup --configure-dotfiles    # saves dotfiles_uri; synced on next start
```

### 4. Verify on the box, remotely

`devbox:exec` runs one command over `coder ssh` and returns its exit code — use it to confirm the fan-out actually worked, and to prototype before moving steps into `install.sh`:

```bash
hogli devbox:exec -- bash -lc 'gh auth status'
hogli devbox:exec -- bash -lc 'claude mcp list'
hogli devbox:exec -- bash -lc 'ls ~/dotfiles && type my-alias'
hogli devbox:exec -n api -- bash -lc 'cd ~/posthog && git status'   # -n targets a named box
```

Always wrap verify commands in `bash -lc '...'`: `coder ssh -- cmd` runs in a **non-login, non-interactive** shell that does not source `~/.bashrc`/`~/.zshrc`, so a bare `gh auth status` reports "command not found" for anything dotfiles put on a login-shell `PATH` (e.g. `~/.local/bin`) — a false negative, not a real failure. Use `--` to separate hogli's flags from the command's own.

`devbox:exec` runs a single command instead of opening a shell (unlike `devbox:ssh`), which is what lets an agent drive a box. It is not side-effect-free: like every `devbox:*` command it first runs the reachability check, which on Linux may `sudo tailscale set --accept-routes` and prompt for a password. Run `hogli devbox:setup` once interactively so routes are already accepted before an agent drives `devbox:exec` unattended.

### 5. Definition of done

Not "this box works." It is: **dotfiles URI set, the secrets you need set, and `devbox:exec` confirms tooling is present** — so the next box you create is configured with zero extra steps. State that explicitly when finishing.

## Answers to the common questions

- **Will my box get removed?** Stop/start and template/AMI updates preserve `/home` (the instance is stopped, not terminated; the template pins `ignore_changes = [ami, user_data]`). A full `devbox:destroy` wipes it — intentional. Because identity lives in dotfiles + user secrets, a destroyed box is recreated fully configured. Don't keep anything irreplaceable only inside a box.
- **Do I need ansible?** No. Dotfiles `install.sh` + user secrets cover personalization declaratively.
- **Multiple boxes?** That is the whole reason to use dotfiles + secrets rather than configuring each box.

## Gotchas

- **Never echo secret values** into the transcript, logs, a PR, or a command line. `devbox:secret:set` reads from a hidden prompt or `--file`; `secret:list` shows names only. Keep it that way.
- **Secrets need a restart.** Setting/changing a secret only affects boxes started afterward — `hogli devbox:restart` to pick it up on a running box.
- **`install.sh` must be executable and committed**, or the dotfiles module silently falls back to plain symlinking and your setup script never runs.
- **`code-server` (browser IDE) has no SSH agent forwarding**, so commit signing via a forwarded key won't work there — use VS Code Desktop / Cursor / JetBrains (SSH-based) when you need to sign.
- **Don't hand-install on a box as the endpoint.** It's fine to prototype with `devbox:exec`, but the change isn't "done" until it's in `install.sh` or a secret.
