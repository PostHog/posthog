# hogli Developer CLI

`hogli` is the unified command-line interface for common PostHog developer workflows. It wraps the existing scripts and tooling in this monorepo to provide a single entry point for spinning up services, running checks, and working on products. These commands mirror the recommendations in the [Developing Locally handbook guide](https://posthog.com/handbook/engineering/developing-locally), so new contributors can rely on a single interface instead of memorising individual scripts.

## Installation & usage

The CLI is shipped with the repository and is available automatically inside the Flox environment.

```bash
flox activate && hogli quickstart
```

### Getting started

New to PostHog development? Run `hogli quickstart` to see the essential commands for getting up and running. It shows:

1. How to start the full dev stack
2. Daily workflows (format code, run checks, etc.)
3. Where to find more commands

### Common workflows

To launch the full development stack (backend, plugin server, workers, frontend):

```bash
hogli start
```

`hogli start` delegates to [`bin/start`](../bin/start), which orchestrates all services through `mprocs`. When you need a one-shot way to verify your code before pushing:

```bash
hogli qa:check
```

`hogli qa:check` (equivalent to the older `hogli check`) runs **fast quality checks** only: linting and building (both complete in ~5 minutes). Tests are intentionally excluded because they're slow (15+ minutes) and shouldn't be bundled with other workflows.

Run tests separately in another terminal:

```bash
# Pick one—tests are slow and shouldn't run together
hogli test:python posthog/api/test/test_foo.py
hogli test:js frontend/src/scenes/Foo/
```

To see all available commands run:

```bash
hogli --help
```

Every subcommand is self-documented. You can append `--help` to any command for detailed options, for example `hogli test:python --help`.

## Design philosophy

hogli follows these principles:

- **Never bundle slow operations** - Tests run separately from lint/build because they take 15+ minutes. Developers should pick **one** test suite per run.
- **Fast feedback loops** - `hogli check` completes in ~5 minutes so you can verify code locally before CI.
- **Thin wrapper layer** - hogli doesn't duplicate tool logic; it delegates to existing scripts (`bin/migrate`, `bin/start`, etc.). If you need advanced options, use the underlying tools directly.
- **Explicit over implicit** - Commands require explicit choices (e.g., `hogli test python` not `hogli test all`) to prevent accidental long-running operations.

## Command mapping

| `hogli` command       | Underlying tools                                                                                     |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| `hogli up`            | [`bin/start`](../bin/start) → `mprocs` (backend, frontends, infra)                                   |
| `hogli services`      | `docker compose -f docker-compose.dev.yml up -d db clickhouse redis redis7 zookeeper kafka`          |
| `hogli test python …` | `pytest` with all trailing arguments forwarded (run individually, not bundled)                       |
| `hogli test js …`     | `pnpm --filter @posthog/frontend run test …` (run individually, not bundled)                         |
| `hogli lint`          | `bin/ruff.sh check` / `pnpm --filter @posthog/frontend run lint` (fast, can run both)                |
| `hogli fmt`           | `bin/ruff.sh format` / `pnpm --filter @posthog/frontend run format` (fast, can run both)             |
| `hogli migrate`       | [`bin/migrate`](../bin/migrate) (Django + ClickHouse migrations)                                     |
| `hogli build`         | `pnpm --filter @posthog/frontend run build` + `pnpm --filter @posthog/frontend run typescript:check` |
| `hogli shell`         | `flox activate`                                                                                      |
| `hogli check`         | Runs `hogli lint` + `hogli build` (skips tests; run them separately)                                 |
| `hogli worktree …`    | [`bin/phw`](../bin/phw) wrapper (delegates to `phw` + `bin/posthog-worktree`)                        |
| `hogli products list` | Reads packages from `products/*/package.json` and Python modules from `products/*`                   |

## Architecture

hogli is built with [Click](https://click.palletsprojects.com/) and discovers all commands from a single manifest:

**Key Components:**

- `hogli/manifest.yaml` - Single source of truth: all command definitions, service metadata, and category grouping
- `hogli/cli.py` - Click CLI framework with dynamic command registration
- `hogli/commands.py` - Command class hierarchy (BinScriptCommand, DirectCommand, CompositeCommand)
- `hogli/manifest.py` - Manifest loading with singleton pattern
- `hogli/validate.py` - Auto-discovery and validation for missing commands
- `bin/` - Executable shell scripts that hogli wraps
- `package.json` - High-level npm commands exposed through hogli

**Help Organization:**
Commands are grouped into categories (see `hogli --help`), auto-formatted in git-style sections. Categories and their display order are defined in the manifest's metadata section.

## Extending the CLI

### Adding a new command

1. **Create the script** in `bin/` or add to `package.json`
2. **Register in manifest.yaml** under the appropriate category:

```yaml
build:
    build:my-feature:
        bin_script: my-feature-script
        description: What this command does
        services: [docker, postgresql] # optional: which services it relates to
```

3. **Optional: mark composition candidates** with a TODO for future conversion to `steps`:

```yaml
docker:
    bin_script: docker
    description: Run all services
    # TODO: candidate for conversion to hogli steps
```

hogli automatically discovers missing bin scripts on every invocation (unless running `meta:check`). Use `hogli meta:check` in CI to enforce manifest completeness.

### Command types

**bin_script** - Delegates to a shell script, always accepts extra args:

```yaml
tool:ruff:
    bin_script: ruff.sh
    description: Python linter
```

**cmd** - Executes a shell command directly:

```yaml
flox:activate:
    cmd: flox activate
    description: Enter dev environment
```

**steps** - Composes multiple hogli commands in sequence:

```yaml
quality:check:
    steps:
        - lint:check
        - build:frontend
    description: Quick quality checks
```

### High-level npm commands

Only expose npm commands that are high-level workflow entry points:

✅ **Good candidates:**

- `pnpm format` - formats all code (backend + frontend together)
- `pnpm schema:build` - orchestrates schema generation pipeline
- `pnpm grammar:build` - generates grammar definitions

❌ **Keep internal:**

- `pnpm build:esbuild` - internal dev server plumbing
- `pnpm typegen:watch` - developer tool
- `pnpm start-http` - implementation detail

Add these to manifest with `cmd:` type and mark with TODO if they orchestrate multiple steps:

```yaml
fmt:all:
    cmd: pnpm format
    description: Format backend and frontend code
    # TODO: candidate for conversion to hogli steps
```

### Service metadata

Commands can declare which services they relate to. This enables `hogli meta:concepts` to show which commands work with each service.

```yaml
command:
    bin_script: script
    services: [docker, kafka, postgresql]
```

Available services are defined in `manifest.yaml` metadata and auto-linked to commands for help text generation.

### CLI-only metadata commands

Two special commands manage hogli itself:

- `hogli meta:check` - Validates manifest, exits with code 1 if scripts are missing. Use in CI.
- `hogli meta:concepts` - Shows all services and which commands use them

## Product utilities

`hogli products list` collates product metadata by reading Turborepo package manifests from the `products/` directory and checking for corresponding Python packages. The output is available as a table or JSON via `--json` for automation.

## Branch switching & worktrees

`hogli worktree` shells out to [`bin/phw`](../bin/phw), which in turn calls [`bin/posthog-worktree`](../bin/posthog-worktree). That means every command supported by the shell helper (`create`, `checkout`, `pr`, `remove`, `list`, and `switch`) works exactly the same way, including future enhancements.

To auto-`cd` into worktrees after creation you can still source [`bin/phw`](../bin/phw) in your shell profile. `hogli worktree` focuses on discoverability and logging, while the sourced function (`phw`) keeps the history-injecting niceties documented in [the Flox multi-instance workflow guide](./FLOX_MULTI_INSTANCE_WORKFLOW.md).

### Shell completions

Typer ships with completion installers for popular shells. Run `hogli --install-completion zsh` (or `bash`, `fish`, etc.) to add completions for the CLI itself. For worktree shortcuts you still get the advanced zsh completion bundled inside [`bin/phw`](../bin/phw) once it is sourced in your profile.
