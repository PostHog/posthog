# Repository Guidelines

## Project Structure & Module Organization
- posthog/: Django backend (manage.py, APIs, HogQL, migrations).
- frontend/: React/TypeScript app UI and assets.
- plugin-server/: Node/TypeScript ingestion and pipelines.
- products/, common/, ee/: Feature modules and shared code (ee contains paid code; avoid changes unless coordinated).
- rust/: Rust utilities (e.g., Cyclotron); playwright/: end-to-end tests; bin/: local tooling; docker-compose.*.yml: local services.

## Build, Test, and Development Commands
- Install deps: `pnpm i` (JS/TS) and `uv sync` (Python 3.11).
- Start dev (multi-process): `pnpm start` (requires `mprocs`; try `bin/start --minimal` if needed).
- Backend tests: `pytest` (use `pytest -k name`, `--cov=posthog` for coverage).
- Frontend tests: `pnpm --filter=@posthog/frontend test`.
- Plugin server tests: `pnpm --dir plugin-server test` (init with `pnpm --dir plugin-server run setup:test`).
- Format all: `pnpm format`; backend only: `pnpm format:backend`; frontend only: `pnpm --filter=@posthog/frontend format`.

## Coding Style & Naming Conventions
- Python: 4-space indent, line length 120, Python 3.11. Lint/format with Ruff (and Black profile). Run `./bin/ruff.sh check --fix` and `./bin/ruff.sh format`.
- JS/TS: Prettier + OXLint; Node 22.x required. Use ESLint/Prettier in `plugin-server/`.
- CSS/SCSS: Stylelint standard + recess order.
- Naming: Python modules/functions snake_case; React components PascalCase; tests `test_*.py` and `*.test.(ts|tsx)`.

## Testing Guidelines
- Frameworks: Pytest (+ pytest-django), Jest for frontend and plugin-server, Playwright for E2E.
- Run unit tests locally without services when possible; for integration tests start dependencies via `docker compose -f docker-compose.dev.yml up -d`.
- Strive for meaningful coverage on new/changed code; prefer small, focused tests.

## Commit & Pull Request Guidelines
- Commits: conventional style prefixes (feat:, fix:, chore:, docs:, with optional scope), e.g., `fix(api): handle empty cohorts`.
- PRs: clear description, rationale, and testing notes; link issues; add screenshots for UI; note migrations or env changes.
- Keep changes scoped; add or update docs where relevant. Avoid modifying `ee/` without prior agreement.

## Security & Config Tips
- Use `.env` for local overrides; never commit secrets.
- Match toolchain: Python 3.11, Node 22, pnpm 9, uv >= 0.7.
