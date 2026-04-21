# PostHog devbox integration

This directory contains the Python glue for managing Coder-hosted PostHog
dev workspaces via `hogli devbox:*` commands. The Coder template itself lives
out-of-repo; this README only documents what the template's startup script
should do.

## Starting the dev stack headlessly in a Coder workspace

Phrocs (the dev process runner invoked by `bin/start`) supports a native
daemon mode. Combine `bin/start --headless` with `hogli start:wait` so the
workspace's `coder_agent.main.startup_script` brings the stack up without
occupying a terminal, and fails loudly if a process crashes during boot.

Paste into the Coder template's agent block:

```hcl
resource "coder_agent" "main" {
  # ...
  startup_script_behavior = "non-blocking"
  startup_script          = <<-EOT
    set -e
    cd /home/coder/posthog

    # Spawn the daemon; returns as soon as phrocs binds its IPC socket.
    ./bin/start --headless

    # Block until every process reports ready, or exit non-zero if a
    # process crashed. Exit 2 means timeout, exit 1 means a crash.
    hogli start:wait --timeout 600 || {
      echo "::warning:: dev stack not fully ready"
      echo "::warning:: inspect with 'hogli start:wait' or attach with 'phrocs attach'"
    }
  EOT
}
```

### Readiness probe as a Coder script (optional)

Surface live health in the Coder workspace UI by adding a lightweight probe:

```hcl
resource "coder_script" "dev_stack_status" {
  agent_id     = coder_agent.main.id
  display_name = "Dev stack status"
  run_on_start = false
  script       = <<-EOT
    cd /home/coder/posthog
    hogli start:wait --timeout 1 --json
  EOT
}
```

## Attaching to a running daemon

Developers who want to see the live TUI:

```sh
phrocs attach
```

This is a polling client that prints process status. Ctrl+C detaches without
stopping the daemon.

## Stopping the stack

```sh
hogli start:stop
```

Graceful: sends `{"cmd":"quit"}` over the IPC socket; falls back to SIGTERM
then SIGKILL via the pidfile if the daemon doesn't exit in time. Idempotent;
exits 0 even when no daemon is running.

## Gotchas

1. **PATH in startup scripts.** Coder's startup script runs under the agent
   user's shell. Ensure `phrocs` and `hogli` are on PATH — typically via a
   preceding `flox activate` or explicit PATH export.
2. **Running as root.** If the template runs startup as root, the IPC socket
   (`/tmp/phrocs-<hash>.sock`) will be owned by root and the developer's SSH
   shell won't have permission to call `hogli start:wait` / `hogli start:stop`.
   Use `sudo -u <workspace-user>` or run startup as the workspace user directly.
3. **Socket path is per-directory.** The socket filename is derived from the
   hash of the absolute repo path. Starting the stack in a different
   directory (e.g. a worktree) produces a different socket; commands run
   against the daemon must be invoked from the same directory.
