---
name: hogli
description: >
  PostHog developer CLI and repo tooling reference. Use when the user mentions
  hogli, asks about repo CLI tools, bin scripts, Makefiles, how to run/build/test/lint,
  or any dev environment commands. Also use when the disk is full, a command fails
  with "No space left on device", or the user asks to free disk space.
---

# hogli - PostHog Developer CLI

Unified CLI for PostHog development. Wraps all repo scripts, bin commands, and tooling behind a single entry point. There is no Makefile — hogli is the equivalent.

Run `hogli --help` to get the full, current command list. Run `hogli <command> --help` for any subcommand.

## Process logging (for agents/debugging)

Where logs land depends on how the stack was launched:

**Detached (`hogli up -d`)** — phrocs writes files under `.posthog/.generated/logs/` on every boot:

- `phrocs.log` — the daemon's own stdio; the place to look when phrocs died at startup and the phrocs MCP tools are unreachable.
- `<process>.log` — per-process output (truncated on each start), where `<process>` matches the phrocs process key (see `bin/mprocs.yaml`).
- `hogli doctor:report` prints the `phrocs.log` path and tails its last lines.

**TUI with `hogli dev:setup --log`, then `hogli start`** — adds a tee wrap per process:

- `/tmp/posthog-<process>.log` — full stdout+stderr; persists in the generated config until `dev:setup` is re-run without `--log`.

When the phrocs MCP is reachable, prefer `mcp__phrocs__get_process_logs` over grepping files.

## Disk full

Preview before deleting anything:

- `hogli doctor:disk --dry-run` estimates each cleanup area: caches, build output, Docker images and the Nix store.
- `hogli worktrees:clean --before 7d --mode deps,build --dry-run` lists idle worktrees whose dependencies and build output can go.
- On a devbox, the `setting-up-devbox` skill covers `hogli devbox:cleanup:disk`.

Show the user the estimates, then run what they approve with `--yes` and one `--area` per approved area.
The cleanup commands need `--yes` or `--dry-run` in an agent shell, because no terminal answers their prompts.

Ask before these, because they lose data or force a full rebuild:

- `--area docker-volumes` drops the local databases.
- `--area rust` and `--area sccache` force a full Rust rebuild.
- `worktrees:clean --mode full` removes whole worktrees. Remove only the worktrees this session created.

## Key references

- `hogli.yaml` — command definitions (source of truth)
- `tools/hogli-commands/hogli_commands/` — PostHog-specific lazy Click command modules
- `tools/hogli/README.md` — framework documentation
- `tools/hogli-commands/README.md` — PostHog commands documentation
