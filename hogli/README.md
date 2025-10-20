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
hogli lint
```

`hogli lint` runs **fast quality checks** only: linting for both Python and JavaScript (completes in ~5 minutes). Tests are intentionally excluded because they're slow (15+ minutes) and shouldn't be bundled with other workflows.

Run tests separately in another terminal:

```bash
# Pick one—tests are slow and shouldn't run together
hogli tests:python posthog/api/test/test_foo.py
hogli tests:js frontend/src/scenes/Foo/
```

To see all available commands run:

```bash
hogli --help
```

Every subcommand is self-documented. You can append `--help` to any command for detailed options, for example `hogli tests:python --help`.

## Design philosophy

hogli follows these principles:

- **Never bundle slow operations** - Tests run separately from lint/build because they take 15+ minutes. Developers should pick **one** test suite per run.
- **Fast feedback loops** - `hogli lint` completes in ~5 minutes so you can verify code locally before CI.
- **Thin wrapper layer** - hogli doesn't duplicate tool logic; it delegates to existing scripts (`bin/migrate`, `bin/start`, etc.). If you need advanced options, use the underlying tools directly.
- **Explicit over implicit** - Commands require explicit choices (e.g., `hogli tests:python` not `hogli test all`) to prevent accidental long-running operations.

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
