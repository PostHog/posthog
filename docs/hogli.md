# hogli Developer CLI

`hogli` is the unified command-line interface for common PostHog developer workflows. It wraps the existing scripts and tooling in this monorepo to provide a single entry point for spinning up services, running checks, and working on products. These commands mirror the recommendations in the [Developing Locally handbook guide](https://posthog.com/handbook/engineering/developing-locally), so new contributors can rely on a single interface instead of memorising individual scripts.

## Installation & usage

The CLI is shipped with the repository and is available automatically inside the Flox environment.

```bash
flox activate && hogli up
```

`hogli up` delegates to [`bin/start`](../bin/start), which launches the full stack (Django backend, plugin server, background workers, Storybook, Docker services, migrations, etc.) through `mprocs`. When you need a one-shot way to make sure your branch is ready for review, reach for:

```bash
hogli check
```

`hogli check` runs the canonical `lint → test → build` workflow in sequence and mirrors the checks that gate CI builds (see the
[`ci-python`](../.github/workflows/ci-python.yml) and [`ci-frontend`](../.github/workflows/ci-frontend.yml) jobs for the
closest equivalents).

To see all available commands run:

```bash
hogli --help
```

Every subcommand is self-documented. You can append `--help` to any command for detailed options, for example `hogli test --help`.

For test runs most engineers target a specific suite. Examples:

```bash
# Run backend tests for a single module
hogli test python posthog/api/test/test_persons.py -k test_person_creation

# Focus on frontend tests matching a Jest path pattern
hogli test js frontend/src/scenes/* --watch
```

## Command mapping

| `hogli` command       | Underlying tools                                                                                     |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| `hogli up`            | [`bin/start`](../bin/start) → `mprocs` (backend, frontends, infra)                                   |
| `hogli services`      | `docker compose -f docker-compose.dev.yml up -d db clickhouse redis redis7 zookeeper kafka`          |
| `hogli test`          | `pytest` + `pnpm --filter @posthog/frontend run test`                                                |
| `hogli test python …` | `pytest` with all trailing arguments forwarded                                                       |
| `hogli test js …`     | `pnpm --filter @posthog/frontend run test …`                                                         |
| `hogli lint`          | `bin/ruff.sh check` / `pnpm --filter @posthog/frontend run lint`                                     |
| `hogli fmt`           | `bin/ruff.sh format` / `pnpm --filter @posthog/frontend run format`                                  |
| `hogli migrate`       | [`bin/migrate`](../bin/migrate) (Django + ClickHouse migrations)                                     |
| `hogli build`         | `pnpm --filter @posthog/frontend run build` + `pnpm --filter @posthog/frontend run typescript:check` |
| `hogli shell`         | `flox activate`                                                                                      |
| `hogli check`         | Runs `hogli lint`, `hogli test`, then `hogli build` sequentially                                     |
| `hogli worktree …`    | [`bin/phw`](../bin/phw) wrapper (delegates to `phw` + `bin/posthog-worktree`)                        |
| `hogli products list` | Reads packages from `products/*/package.json` and Python modules from `products/*`                   |

## Extending the CLI

The CLI is implemented with [Typer](https://typer.tiangolo.com/), so adding new commands is straightforward:

1. Edit [`hogli/cli.py`](../hogli/cli.py).
2. Add a new function decorated with `@app.command()` (or add a new Typer sub-app for larger feature areas).
3. Use the helper `_run([...])` to execute existing repository scripts or external tools. The helper automatically prints the command and converts failures into friendly error messages.
4. Document the new command in this file so developers can discover it quickly.

When wrapping new workflows prefer calling the existing bash scripts or package.json tasks. This keeps `hogli` as a thin compatibility layer and reduces churn when the underlying implementation changes.

## Product utilities

`hogli products list` collates product metadata by reading Turborepo package manifests from the `products/` directory and checking for corresponding Python packages. The output is available as a table or JSON via `--json` for automation.

## Branch switching & worktrees

`hogli worktree` shells out to [`bin/phw`](../bin/phw), which in turn calls [`bin/posthog-worktree`](../bin/posthog-worktree). That means every command supported by the shell helper (`create`, `checkout`, `pr`, `remove`, `list`, and `switch`) works exactly the same way, including future enhancements.

To auto-`cd` into worktrees after creation you can still source [`bin/phw`](../bin/phw) in your shell profile. `hogli worktree` focuses on discoverability and logging, while the sourced function (`phw`) keeps the history-injecting niceties documented in [the Flox multi-instance workflow guide](./FLOX_MULTI_INSTANCE_WORKFLOW.md).

### Shell completions

Typer ships with completion installers for popular shells. Run `hogli --install-completion zsh` (or `bash`, `fish`, etc.) to add completions for the CLI itself. For worktree shortcuts you still get the advanced zsh completion bundled inside [`bin/phw`](../bin/phw) once it is sourced in your profile.
