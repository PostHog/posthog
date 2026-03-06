# PostHog Development Guide

## Codebase Structure

- Key entry points: `posthog/api/__init__.py` (URL routing), `posthog/settings/web.py` (Django settings, INSTALLED_APPS), `products/` (product apps)
- [Monorepo layout](docs/internal/monorepo-layout.md) - high-level directory structure (products, services, common)
- [Products README](products/README.md) - how to create and structure products
- [Products architecture](products/architecture.md) - DTOs, facades, isolated testing

## Commands

- Environment:
  - Auto-detect flox environment before running terminal commands
  - If flox is available, and you run into trouble executing commands, try with `flox activate -- bash -c "<command>"` pattern
    - Never use `flox activate` in interactive sessions (it hangs if you try)
  - If local hooks fail with missing Husky bootstrap files (for example `.husky/_/husky.sh`) or missing `lint-staged`, run `pnpm install --frozen-lockfile --filter=.` once in the repo root
- Tests:
  - All tests: `pytest`
  - Single test: `pytest path/to/test.py::TestClass::test_method`
  - Product tests (Turbo): `pnpm turbo run backend:test --filter=@posthog/products-<name>`
  - Frontend: `pnpm --filter=@posthog/frontend test`
  - Single frontend test: `pnpm --filter=@posthog/frontend jest <test_file>`
- Lint:
  - Python:
    - `ruff check . --fix` and `ruff format .`
    - Do not run mypy for type checks. It takes too long.
  - Frontend: `pnpm --filter=@posthog/frontend format`
  - TypeScript check: `pnpm --filter=@posthog/frontend typescript:check`
- Build:
  - Frontend: `pnpm --filter=@posthog/frontend build`
  - Start dev: `./bin/start`
- OpenAPI/types: `hogli build:openapi` (regenerate after changing serializers/viewsets)
- New product: `bin/hogli product:bootstrap <name>`
- LSP: Pyright is configured against the flox venv. Prefer LSP (`goToDefinition`, `findReferences`, `hover`) over grep when navigating or refactoring Python code.

## Commits and Pull Requests

Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages and PR titles.

### Commit types

- `feat`: New feature or functionality (touches production code)
- `fix`: Bug fix (touches production code)
- `chore`: Non-production changes (docs, tests, config, CI, refactoring agents instructions, etc.)
- Scope convention: use `llma` for LLM analytics changes (for example, `feat(llma): ...`)

### Format

```text
<type>(<scope>): <description>
```

Examples:

- `feat(insights): add retention graph export`
- `fix(cohorts): handle empty cohort in query builder`
- `chore(ci): update GitHub Actions workflow`
- `chore: update AGENTS.md instructions`

### Rules

- Scope is optional but encouraged when the change is specific to a feature area
- Description should be lowercase and not end with a period
- Keep the first line under 72 characters

## Security

See [.agents/security.md](.agents/security.md) for SQL, HogQL, and semgrep security guidelines.

## Architecture guidelines

- API views should declare request/response schemas — prefer `@validated_request` from `posthog.api.mixins` or `@extend_schema` from drf-spectacular. Plain `ViewSet` methods that validate manually need `@extend_schema(request=YourSerializer)` — without it, drf-spectacular can't discover the request body and generated code gets empty schemas
- Django serializers are the source of truth for frontend API types — `hogli build:openapi` generates TypeScript via drf-spectacular + Orval. Generated files (`api.schemas.ts`, `api.ts`) live in `frontend/src/generated/core/` and `products/{product}/frontend/generated/` — don't edit them manually, change serializers and rerun. See [type system guide](docs/published/handbook/engineering/type-system.md) for the full pipeline
- MCP tools are generated from the same OpenAPI spec — see [implementing MCP tools](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) for the YAML config and codegen workflow
- When touching a viewset or serializer, check that it has proper schema annotations. If a `ViewSet` method is missing `@extend_schema`, or a serializer field is missing `help_text`, fix it while you're there — these flow into generated frontend types and MCP tool schemas, so gaps compound downstream
- New features should live in `products/` — read [products/README.md](products/README.md) for layout and setup. When _creating a new_ product, follow [products/architecture.md](products/architecture.md) (DTOs, facades, isolation). Most existing products are legacy moves and don't use this architecture yet — match the patterns already in the product you're editing
- Always filter querysets by `team_id` — in serializers, access the team via `self.context["get_team"]()`
- **Do not add domain-specific fields to the `Team` model.** Use a Team Extension model instead — see `posthog/models/team/README.md` for the pattern and helpers

## Important rules for Code Style

- Python: Use type hints, follow mypy strict rules
- Frontend: TypeScript required, explicit return types
- Frontend: If there is a kea logic file, write all business logic there, avoid React hooks at all costs.
- Imports: Use oxfmt import sorting (automatically runs on format), avoid direct dayjs imports (use lib/dayjs)
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: should not duplicate the code below, don't tell me "this finds the shortest username" tell me _why_ that is important, if it isn't important don't add a comment, almost never add a comment
- Python tests: do not add doc comments
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- any tests: prefer to use parameterized tests, think carefully about what input and output look like so that the tests exercise the system and explain the code to the future traveller
- Python tests: in python use the parameterized library for parameterized tests, every time you are tempted to add more than one assertion to a test consider (really carefully) if it should be a parameterized test instead
- Reduce nesting: Use early returns, guard clauses, and helper methods to avoid deeply nested code

## General

- Markdown: prefer semantic line breaks; no hard wrapping
- Use American English spelling
- When mentioning PostHog products, the product names should use Sentence casing, not Title Casing. For example, 'Product analytics', not 'Product Analytics'. Any other buttons, tab text, tooltips, etc should also all use Sentence casing. For example, 'Save as view' instead of 'Save As View'.

## Skills

Skills are created inside [.agents/skills](.agents/skills/) by default and then symlinked to [.claude/skills](.claude/skills). Make sure you always treat `.agents/skills` as the source of truth.
