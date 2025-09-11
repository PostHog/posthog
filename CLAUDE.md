# PostHog Development Guide

## Commands

- Environment:
    - Auto-detect flox environment before running terminal commands
    - If flox is available: ALWAYS use `flox activate -- bash -c "<command>"` pattern
    - Never use `flox activate` in interactive sessions (it hangs)
- Tests:
    - All tests: `pytest`
    - Single test: `pytest path/to/test.py::TestClass::test_method`
    - Frontend: `pnpm --filter=@posthog/frontend test`
    - Single frontend test: `pnpm --filter=@posthog/frontend jest <test_file>`
- Lint:
    - Python: `ruff .`
    - Frontend: `pnpm --filter=@posthog/frontend format`
    - TypeScript check: `pnpm --filter=@posthog/frontend typescript:check`
- Build:
    - Frontend: `pnpm --filter=@posthog/frontend build`
    - Start dev: `./bin/start`

## Important rules for Code Style

- Python: Use type hints, follow mypy strict rules
- Frontend: TypeScript required, explicit return types
- Imports: Use prettier-plugin-sort-imports (automatically runs on format), avoid direct dayjs imports (use lib/dayjs)
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: should not duplicate the code below, don't tell me "this finds the shortest username" tell me _why_ that is important, if it isn't important don't add a comment, almost never add a comment 
- Python tests: do not add doc comments
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- any tests: prefer to use parameterized tests, think carefully about what input and output look like so that the tests exercise the system and explain the code to the future traveller
- Python tests: in python use the parameterized library for parameterized tests, every time you are tempted to add more than one assertion to a test consider (really carefully) if it should be a parameterized test instead
- always remember that there is a tension between having the fewest parts to code (a simple system) and having the most understandable code (a maintainable system). structure code to balance these two things.
