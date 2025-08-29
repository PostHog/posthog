# Repository Guidelines

## Project Structure & Module Organization
- Backend: Django app in `posthog/` (entry: `manage.py`), with PostgreSQL and ClickHouse integrations. Tests live under `posthog/test/`.
- Frontend: React/TypeScript in `frontend/` and feature modules under `products/`. Shared UI/build utils in `common/`.
- Plugin server: Node-based in `plugin-server/`.
- Services: Rust workers in `rust/`.
- Tooling: Dev scripts in `bin/`, Docker Compose files (`docker-compose.*.yml`) for local stack.

## Build, Test, and Development Commands
- Setup: `pnpm install` (Node 22), Python deps with `uv sync` (Python 3.11).
- Start (recommended): `bin/start` (uses mprocs + Docker to run DBs, backend, workers, plugin server, frontend). Useful flags: `--minimal`, `--vite`.
- Migrations: `python manage.py migrate` and `python manage.py migrate_clickhouse`.
- Frontend dev: `pnpm --filter=@posthog/frontend start`.
- Storybook: `pnpm storybook`.

## Coding Style & Naming Conventions
- Python: Black (120 cols), Ruff + isort grouping configured in `pyproject.toml`. Use snake_case for functions/vars, `PascalCase` for classes. Run `./bin/ruff.sh check --fix` and `./bin/ruff.sh format`.
- TypeScript/JS: Prettier 3, Oxlint, Stylelint. Run `pnpm --filter=@posthog/frontend lint` and `pnpm --filter=@posthog/frontend format`.
- Imports: Sorted by tooling (pre-commit via `lint-staged`).

## Testing Guidelines
- Backend: `pytest` (Django settings via `pytest.ini`). Common markers: `ee`, `clickhouse_only`. Example: `pytest -q posthog/test/`.
- Frontend unit: `pnpm --filter=@posthog/frontend test` (Jest). Sharding supported via `SHARD_INDEX`/`SHARD_COUNT`.
- E2E: Playwright setup available (`docker-compose.playwright.yml`) when needed.

## Commit & Pull Request Guidelines
- Commits: Use short, imperative subjects with type prefixes (e.g., `feat: ...`, `fix: ...`, `chore: ...`). Keep scope clear.
- PRs: Provide a concise description, link related issues, add screenshots for UI changes, and note migrations. Ensure tests/lints pass.

## Security & Configuration Tips
- Local env: `.env` is loaded by `bin/start`. Do not commit secrets.
- Defaults: `bin/start` configures common dev URLs and telemetry flags; use `--enable-tracing` to debug tracing locally.
