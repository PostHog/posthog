# PostHog Development Guide

## Commands
- Tests: 
  - All tests: `pytest`
  - Single test: `pytest path/to/test.py::TestClass::test_method`
  - Frontend: `pnpm --filter=@poshog/frontend test`
  - Single frontend test: `pnpm --filter=@poshog/frontend test <test_file>`
- Lint: 
  - Python: `ruff .` 
  - Frontend: `pnpm --filter=@poshog/frontend format`
  - TypeScript check: `pnpm --filter=@poshog/frontend typescript:check`
- Build:
  - Frontend: `pnpm --filter=@poshog/frontend build`
  - Start dev: `./bin/start`

## Code Style
- Python: Use type hints, follow mypy strict rules
- Frontend: TypeScript required, explicit return types
- Imports: Use simple-import-sort, avoid direct dayjs imports (use lib/dayjs)
- Components: Use Lemon components (LemonButton, LemonInput, etc.) not antd
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: Leave comments to explain tricky areas of the code or to explain WHY something is there, but don't just leave comments everywhere, the code should be default readable
- Comments: should not duplicate the code below, don't tell me "this finds the shortest username" tell me _why_ that is important, if it isn't important don't add a comment
- Python tests: do not need doc comments, give them good names, and leave off with the comments 
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- any tests: prefer to use parameterized tests, think carefully about what input and output look like so that the tests exercise the system and explain the code to the future traveller
- parameterized tests: in python use the parameterized library for parameterized tests
- always remember that there is a tension between having the fewest parts to code (a simple system) and having the most understandable code (a maintainable system). structure code to balance these two things.