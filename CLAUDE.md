# PostHog Development Guide

## Commands
- Tests: 
  - All tests: `pytest`
  - Single test: `pytest path/to/test.py::TestClass::test_method`
  - Frontend: `cd frontend && pnpm test`
  - Single frontend test: `cd frontend && pnpm jest <test_file>`
- Lint: 
  - Python: `ruff .` 
  - Frontend: `cd frontend && pnpm format`
  - TypeScript check: `cd frontend && pnpm typescript:check`
- Build:
  - Frontend: `cd frontend && pnpm build`
  - Start dev: `./bin/start`

## Code Style
- Python: Use type hints, follow mypy strict rules
- Frontend: TypeScript required, explicit return types
- Imports: Use simple-import-sort, avoid direct dayjs imports (use lib/dayjs)
- Components: Use Lemon components (LemonButton, LemonInput, etc.) not antd
- CSS: Use utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: Leave comments to explain tricky areas of the code or to explain WHY something is there, but don't just leave comments everywhere, the code should be default readable