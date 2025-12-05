# hogli Developer CLI

`hogli` is the unified command-line interface for common PostHog developer workflows. It wraps the existing scripts and tooling in this monorepo to provide a single entry point for spinning up services, running checks, and working on products. These commands mirror the recommendations in the [Developing Locally handbook guide](https://posthog.com/handbook/engineering/developing-locally), so new contributors can rely on a single interface instead of memorising individual scripts.

---

## Part 1: Using hogli (user guide - will move to handbook)

This section is for all developers using hogli. These docs will move to the handbook.

### Installation & usage

hogli is shipped with the repository. There are two ways to use it:

**With Flox (recommended):**

```bash
flox activate  # hogli is available in PATH
hogli quickstart
```

**Without Flox:**

```bash
uv sync        # Install Python dependencies (includes Click)
bin/hogli quickstart
```

The Flox environment adds `hogli` to your PATH via a symlink. Without Flox, use `bin/hogli` directly or add `bin/` to your PATH.

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
hogli test:python posthog/api/test/test_foo.py
hogli test:js frontend/src/scenes/Foo/
```

To see all available commands run:

```bash
hogli --help
```

Every subcommand is self-documented. You can append `--help` to any command for detailed options, for example `hogli test:python --help`.

### Design philosophy

Hogli follows these principles:

- **Thin wrapper layer** - hogli doesn't duplicate tool logic; it delegates to existing scripts (`bin/migrate`, `bin/start`, etc.). If you need advanced options, use the underlying tools directly.
- **Explicit over implicit** - Commands require explicit choices (e.g., `hogli test:python` not `hogli test all`) to prevent accidental long-running operations.

---

## Part 2: Extending hogli (developer guide - stays in repo)

This section is for developers extending hogli itself. These docs stay in the repository.

### Architecture

hogli is built with [Click](https://click.palletsprojects.com/) and discovers all commands from a single manifest:

**Key Components:**

- `common/hogli/manifest.yaml` - Single source of truth: all command definitions, service metadata, and category grouping
- `common/hogli/commands.py` - **Developer extension point** for adding custom Click commands
- `common/hogli/core/cli.py` - CLI framework with dynamic command registration
- `bin/` - Executable shell scripts that hogli wraps
- `package.json` - High-level npm commands exposed through hogli

**Structure:**

- `common/hogli/core/` - Framework internals (don't modify directly)
- `common/hogli/manifest.yaml` - Developer configuration
- `common/hogli/commands.py` - Developer extension point for Click commands

**Help Organization:**
Commands are grouped into categories (see `hogli --help`), auto-formatted in git-style sections. Categories and their display order are defined in the manifest's metadata section.

### Extending the CLI

#### Adding a new command - Decision tree

There are 5 ways to add commands to hogli. Use this decision tree to choose the right approach:

```text
Need to add a new command?
│
├─ Is it a custom Python Click command with workflow logic?
│  └─ YES → Add @cli.command() in common/hogli/commands.py
│     When: Need Python logic for dev workflows (not just shell commands)
│     Examples: Custom validators, multi-step Python logic, Click argument parsing
│
├─ Does it manipulate hogli itself (meta-level operations)?
│  └─ YES → Add @cli.command() in common/hogli/core/cli.py
│     When: Command validates manifest, shows framework info, or uses hogli internals
│     Examples: quickstart, meta:check, meta:concepts
│
├─ Does it orchestrate multiple existing hogli commands?
│  └─ YES → Add to manifest.yaml with steps: [cmd1, cmd2, ...]
│     When: Combines hogli commands in sequence (no shell logic needed)
│     Examples: dev:reset (services down → up → migrate → demo-data)
│
├─ Does it need shell scripting (loops, conditionals, multi-step logic)?
│  └─ YES → Create bin/my-script + add to manifest.yaml with bin_script: my-script
│     When: Needs bash loops, retry logic, or complex shell operations
│     Examples: check:postgres (retry loop), migrate (orchestrates multiple tools)
│
└─ Is it a simple shell command with no logic?
   └─ YES → Add to manifest.yaml with cmd: "your command here"
      When: Single shell command, can be one-liners like docker compose or pnpm
      Examples: docker:services:up, lint, format, test:python
```

**Note on Python commands:**

- **Developer workflow commands** → Add to `common/hogli/commands.py` (main extension point)
- **Framework/meta commands** → Add to `common/hogli/core/cli.py` (rarely needed)

**Auto-discovery:**
hogli automatically discovers missing bin scripts on every invocation (except `meta:check`). Auto-discovered commands are marked as `hidden: true` by default until reviewed. Use `hogli meta:check` in CI to enforce manifest completeness.

**Hiding commands:**
Add `hidden: true` to any command to hide it from `--help` output while keeping it callable. Use for:

- **Deprecated commands** - Still work for backward compatibility but not advertised
- **Production-only commands** - Docker/deployment commands not used in local dev
- **Specialist/advanced tools** - Low-level utilities for specific use cases
- **Duplicates/aliases** - Alternative names kept for compatibility

Hidden commands are still fully functional and can be invoked directly (e.g., `hogli docker:deprecated`), they just don't clutter the help output.

#### Command type reference

Use the decision tree above to choose, then reference these examples for syntax:

**1. Click command in commands.py** - For developer workflow commands:

```python
# In common/hogli/commands.py
from hogli.core.cli import cli
import click

@cli.command(name="my-workflow", help="Custom workflow command")
@click.option('--verbose', is_flag=True, help='Verbose output')
def my_workflow(verbose: bool) -> None:
    """Custom workflow implementation."""
    # Your Python logic here
    click.echo("Running custom workflow...")
```

**2. Click command in core/cli.py** - For meta/framework commands (rarely needed):

```python
# In common/hogli/core/cli.py
@cli.command(name="meta:my-command", help="Does something with hogli internals")
def my_meta_command() -> None:
    """Command implementation."""
    from hogli.core.manifest import load_manifest
    manifest = load_manifest()
    # Your logic here
    click.echo("Done!")
```

**3. steps** - Orchestrates hogli commands (no shell needed):

```yaml
dev:reset:
  steps:
    - docker:services:down
    - docker:services:up
    - migrations:run
    - dev:demo-data
  description: Full reset and reload
```

**4. bin_script** - Delegates to shell script with logic:

Create `bin/my-script`:

```bash
#!/usr/bin/env bash
set -e
# Shell logic: loops, conditionals, etc.
for i in {1..5}; do
    echo "Attempt $i..."
    if some_check; then break; fi
done
```

Add to manifest:

```yaml
check:my-service:
  bin_script: my-script
  description: Check if service is ready
  services: [docker]
```

**5. cmd** - Simple shell one-liner:

```yaml
lint:
  cmd: ./bin/ruff.sh check . && pnpm --filter=@posthog/frontend run lint
  description: Run code quality checks
```

**Hiding commands** - Add `hidden: true` to keep callable but remove from help:

```yaml
docker:deprecated:
  bin_script: docker
  description: '[DEPRECATED] Use `hogli start` instead'
  hidden: true # Still works, just not shown in --help
```

#### Guidelines for exposing npm commands

Only expose npm commands that are **high-level workflow entry points**:

✅ **Good - user-facing workflows:**

- `pnpm format` (formats all code)
- `pnpm schema:build` (orchestrates schema pipeline)
- `pnpm grammar:build` (generates grammar definitions)

❌ **Keep internal - implementation details:**

- `pnpm build:esbuild` (dev server plumbing)
- `pnpm typegen:watch` (internal dev tool)
- `pnpm start-http` (server implementation)

Add workflow commands with `cmd:` type. If they could be broken into hogli steps later, mark with TODO:

```yaml
format:
  cmd: pnpm format
  description: Format backend and frontend code
  # TODO: candidate for conversion to hogli steps
```

#### Service metadata

Commands can declare which services they relate to. This enables `hogli meta:concepts` to show which commands work with each service.

```yaml
command:
  bin_script: script
  services: [docker, kafka, postgresql]
```

Available services are defined in `manifest.yaml` metadata and auto-linked to commands for help text generation.

#### CLI-only metadata commands

Two special commands manage hogli itself:

- `hogli meta:check` - Validates manifest, exits with code 1 if scripts are missing. Use in CI.
- `hogli meta:concepts` - Shows all services and which commands use them
