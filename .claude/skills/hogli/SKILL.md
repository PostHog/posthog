---
name: hogli
description: PostHog developer CLI (hogli) reference. Use when the user invokes /hogli to understand available commands, process logging, and dev environment setup.
---

# hogli - PostHog Developer CLI

hogli is the unified CLI for PostHog development. It wraps existing scripts and tooling via a manifest-driven architecture built on Click.

## Process logging for agents

To make mprocs process output available as files (useful for coding agents and debugging):

```bash
hogli dev:setup --log
```

This runs the interactive setup wizard and enables logging. Each mprocs process will pipe output to `/tmp/posthog-<process-name>.log` via `tee`. After setup, `hogli start` will use the saved config automatically.

Log file locations:

- `/tmp/posthog-django.log` - Django backend
- `/tmp/posthog-frontend.log` - Vite frontend dev server
- `/tmp/posthog-celery.log` - Celery worker
- `/tmp/posthog-nodejs.log` - Node.js ingestion/CDP
- `/tmp/posthog-temporal.log` - Temporal worker

To read logs: `cat /tmp/posthog-django.log` or `tail -f /tmp/posthog-frontend.log`

## Common commands

### Starting services

| Command                 | What it does                                           |
| ----------------------- | ------------------------------------------------------ |
| `hogli start`           | Launch full dev stack via mprocs                       |
| `hogli dev:setup`       | Interactive wizard to configure which services to run  |
| `hogli dev:setup --log` | Same wizard but enables file logging for all processes |
| `hogli dev:reset`       | Full reset: wipe volumes, migrate, load demo data      |

### Code quality

| Command                 | What it does                         |
| ----------------------- | ------------------------------------ |
| `hogli lint`            | Run Python (ruff) and JS/TS linting  |
| `hogli format`          | Format all backend and frontend code |
| `hogli format:python`   | Format Python files only             |
| `hogli format:js`       | Format JS/TS files only              |
| `hogli lint:python:fix` | Auto-fix Python linting issues       |

### Testing

| Command                    | What it does                |
| -------------------------- | --------------------------- |
| `hogli test:python <path>` | Run Python tests (`pytest`) |
| `hogli test:js <path>`     | Run JS tests (`pnpm jest`)  |

### Build and schema generation

| Command                | What it does                                             |
| ---------------------- | -------------------------------------------------------- |
| `hogli build:schema`   | Generate all schema definitions (JSON, Python, versions) |
| `hogli build:openapi`  | Generate OpenAPI schema and TypeScript types             |
| `hogli build:grammar`  | Generate HogQL grammar definitions                       |
| `hogli build:frontend` | Build frontend packages                                  |

### Migrations

| Command                  | What it does                                              |
| ------------------------ | --------------------------------------------------------- |
| `hogli migrations:run`   | Run all database migrations (ClickHouse, Postgres, async) |
| `hogli migrations:check` | Verify migrations are ready without applying              |

### Health checks

| Command                  | What it does                     |
| ------------------------ | -------------------------------- |
| `hogli check:postgres`   | Wait for PostgreSQL to be ready  |
| `hogli check:clickhouse` | Wait for ClickHouse to be ready  |
| `hogli services:ready`   | Wait for all core infrastructure |

### Docker

| Command                        | What it does                     |
| ------------------------------ | -------------------------------- |
| `hogli docker:services:down`   | Stop Docker services             |
| `hogli docker:services:remove` | Stop and wipe all Docker volumes |

### Other useful commands

| Command                | What it does                            |
| ---------------------- | --------------------------------------- |
| `hogli quickstart`     | Show essential getting started commands |
| `hogli dev:demo-data`  | Generate demo data for local testing    |
| `hogli dev:shell-plus` | Django shell with auto-imported models  |
| `hogli dev:api-key`    | Create a stable local API key           |
| `hogli --help`         | List all commands by category           |

## Key files

- `common/hogli/manifest.yaml` - All command definitions (single source of truth)
- `common/hogli/commands.py` - Custom Click commands extension point
- `common/hogli/devenv/` - Intent-based dev environment (wizard, generator, mprocs config)
- `common/hogli/README.md` - Full developer documentation
- `bin/hogli` - Entry point script
