---
name: hogli
description: >
  PostHog developer CLI and repo tooling reference. Use when the user mentions
  hogli, asks about repo CLI tools, bin scripts, Makefiles, how to run/build/test/lint,
  or any dev environment commands.
---

# hogli - PostHog Developer CLI

Unified CLI for PostHog development. Wraps all repo scripts, bin commands, and tooling behind a single entry point. There is no Makefile — hogli is the equivalent.

Run `hogli --help` to get the full, current command list. Run `hogli <command> --help` for any subcommand.

## Process logging (for agents/debugging)

`hogli dev:setup --log` enables file logging for all mprocs processes. Logs go to `/tmp/posthog-<process>.log` (django, frontend, celery, nodejs, temporal).

## Key references

- `common/hogli/manifest.yaml` — command definitions (source of truth)
- `common/hogli/commands.py` — extension point for custom Click commands
- `common/hogli/README.md` — full developer and architecture docs
