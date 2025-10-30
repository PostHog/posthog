# Tilt development workflow

Tilt provides a single entry point for orchestrating the PostHog development stack. It replaces the manual `docker compose` + `mprocs` workflow from `bin/start`, while still relying on the same commands and scripts under the hood.

## Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) or [OrbStack](https://orbstack.dev/) running locally
- [Tilt](https://tilt.dev) ≥ v0.33: `brew install tilt-dev/tap/tilt`, `choco install tilt`, or download the binary from the [Tilt releases page](https://github.com/tilt-dev/tilt/releases)
- Existing language toolchains (Python via `uv`, Node via `pnpm`, Rust) as already required by `bin/start`

> [!TIP]
> Tilt automatically installs the MaxMind database via the `download-mmdb` resource before any application processes start.

## Getting started

Run Tilt from the repository root:

```bash
# Default profile (minimal - recommended)
tilt up
```

Tilt streams the same commands that `bin/mprocs.yaml` defines. When code changes, Tilt restarts the affected process so you get the same live reload experience as before.

Access the **Tilt UI at http://localhost:10350/** to view service status, logs, and enable/disable services.

To tear everything down, press `Ctrl+C` in the Tilt terminal or run `tilt down` in another shell.

## Profiles

The `TILT_PROFILE` environment variable mirrors the existing `--minimal`/default split from `bin/start` and adds a "core" middle ground. **All services (application and infrastructure) are always visible in the Tilt UI.** The profile only controls which services auto-start when you run `tilt up`:

| Profile | Command                     | Auto-enabled services                                                                                       |
| ------- | --------------------------- | ----------------------------------------------------------------------------------------------------------- |
| minimal | `tilt up` (default)         | Django backend, Celery worker, plugin server (no restart loop), frontend, capture services, core migrations |
| core    | `TILT_PROFILE=core tilt up` | Minimal profile plus Celery beat, Dagster, essential Temporal workers, embedding worker                     |
| full    | `TILT_PROFILE=full tilt up` | Everything in `bin/mprocs.yaml`, including specialized Temporal queues and Rust services                    |

The profile only controls auto-start behavior. Enable/disable services on-demand via the UI using these service groups:

- **minimal** - Essential services (backend, frontend, core infra, basic rust services)
- **core** - Useful additions (dagster, temporal workers, embedding-worker, temporal infra)
- **full** - Specialized services (max-ai worker, cymbal, monitoring UIs, dev tools)
- **migrations** (4 services) - Database setup tasks (run once)
- **fixtures** (1 service) - Demo data generation (manual trigger)

You can toggle individual services or entire groups in the UI without restarting Tilt.

### Manual/optional resources

Some developer tools are available but do not auto-start:

- `storybook` – launches the component library (`trigger_mode=manual`)
- `hedgebox-dummy` – example integration app (`trigger_mode=manual`)

Trigger them from the Tilt UI or with `tilt trigger <resource>` when needed.

## Resource layout

Tilt defines one resource per command in `bin/mprocs.yaml`/`bin/mprocs-minimal.yaml`:

- **Infrastructure** is still powered by Docker Compose. Tilt loads `docker-compose.dev.yml` (or the minimal variant) and tags every service with an `infra` label in the UI.
- **Python services** (`backend`, `celery-*`, Temporal workers, Dagster, migrations) reuse the existing `uv sync` and `manage.py` commands.
- **Node services** (`frontend`, `plugin-server`, Storybook) call the same wrapper scripts used today.
- **Rust services** (`capture`, `feature-flags`, etc.) run through `bin/start-rust-service` and watch the `rust/` workspace.
- **Bootstrap tasks** (`download-mmdb`, migrations, demo data) auto-run once on startup and can be retriggered manually. Demo data
  seeding waits for the migrations and Dagster UI to be ready before it executes.

File watches exclude heavy directories like `node_modules`, `.venv`, and `rust/target` to keep rebuilds responsive.

## Observability defaults

The Tiltfile exports the same environment variables that `bin/start` configures, including:

- OpenTelemetry defaults (disabled automatically in the `minimal` profile)
- Dagster workspace configuration (`$DAGSTER_HOME`, host, and port)
- Demo URLs like `BILLING_SERVICE_URL` and `HOG_HOOK_URL`

Override any of them via your shell environment before launching Tilt.

## Accessing logs and status for AI coding assistants

Tilt provides structured APIs that make it ideal for AI coding assistants, offering both log access and resource status inspection:

```bash
# Stream logs from a specific service (equivalent to mprocs-with-logging)
tilt logs backend -f

# Get logs from multiple services
tilt logs backend celery-worker -f

# Get current logs without following
tilt logs frontend

# List all available resources with structured output
tilt get uiresource

# Check if celery is running (structured YAML/JSON output)
tilt get uiresource celery-worker -o yaml
tilt get uiresource celery-worker -o json

# Get status of all resources as JSON for parsing
tilt get uiresource -o json
```

AI coding assistants can use these commands to:

- Access any service's logs without managing `/tmp/` files
- Check resource status programmatically (Enabled/Disabled, Running/Stopped, etc.)
- Parse structured output instead of terminal UI layouts
- Query the Tilt API server at `localhost:10350` for real-time status

This provides better visibility than mprocs-with-logging since agents can both read logs **and** query service state programmatically.

## Troubleshooting

- Verify Tilt configuration: `tilt doctor`
- Restart a single service: `tilt trigger <resource>`
- Clean up Docker resources: `docker compose -f docker-compose.dev.yml down` and then re-run `tilt up`
- If Docker Compose fails to start, check the Tilt UI logs for the `infra`-labelled resources

For more context on the underlying commands, see [`bin/start`](../../bin/start) and the `hogli` manifest entries in `common/hogli/manifest.yaml`.
