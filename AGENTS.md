# PostHog Development Guide

## Codebase Structure

- Key entry points: `posthog/api/__init__.py` (URL routing), `posthog/settings/web.py` (Django settings, INSTALLED_APPS), `products/` (product apps)
- [Monorepo layout](docs/internal/monorepo-layout.md) - high-level directory structure (products, services, common)
- [Products README](products/README.md) - how to create and structure products
- [Products architecture](products/architecture.md) - DTOs, facades, isolated testing

## Commands

- Environment:
  - Use flox when available — prefer `flox activate -- bash -c "<command>"` if commands fail
    - Never use `flox activate` in interactive sessions (it hangs if you try)
- Tests:
  - Universal: `hogli test <file_or_directory>` — auto-detects test type (Python, Jest, Playwright, Rust, Go)
  - Single test: `hogli test path/to/test.py::TestClass::test_method`
  - Watch mode: `hogli test path/to/test.py --watch`
  - Changed files only: `hogli test --changed`
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

### PR descriptions

**Required:** Before creating any PR, read `.github/pull_request_template.md` and use its exact section structure.
Do not invent a different format.
Always uncomment and fill the `## LLM context` section for agent-authored PRs.
Keep descriptions high-level, focusing on rationale and architecture for the human reviewer.

### Rules

- Scope is optional but encouraged when the change is specific to a feature area
- Description should be lowercase and not end with a period
- Keep the first line under 72 characters

### Public open source repo guidance

This repository is public and all commit messages, pull request titles, and pull request descriptions must be safe for public readers.

- Never mention internal-only systems, private incidents, customer data, private Slack threads, unreleased roadmap details, or security-sensitive implementation details.
- Use product-facing and code-facing context that a public OSS contributor could understand from this repository alone.
- If context is sensitive, summarize it at a high level without naming internal tools, accounts, or people.
- Avoid citing private operational scale or incident metrics (for example, exact affected team counts, internal row-volume anecdotes, or customer-specific performance numbers) unless that data is already public and linkable.

Examples:

- ✅ `fix(insights): handle missing series color in trend export`
- ❌ `fix: patch issue found in acme-co prod workspace after sales escalation` — references internal customer
- ❌ `fix: will run fine on our 12 million rows there now` — leaks private operational scale

## CI / GitHub Actions

- `.nvmrc` controls the Node.js version for all CI workflows (via `actions/setup-node`) — changing it affects every CI job that runs Node
- Every job in `.github/workflows/` must declare `timeout-minutes` — prevents stuck runners from burning credits indefinitely

## Security

See [.agents/security.md](.agents/security.md) for SQL, HogQL, and semgrep security guidelines.

## Architecture guidelines

- API views should declare request/response schemas — prefer `@validated_request` from `posthog.api.mixins` or `@extend_schema` from drf-spectacular. Plain `ViewSet` methods that validate manually need `@extend_schema(request=YourSerializer)` — without it, drf-spectacular can't discover the request body and generated code gets empty schemas
- Django serializers are the source of truth for frontend API types — `hogli build:openapi` generates TypeScript via drf-spectacular + Orval. Generated files (`api.schemas.ts`, `api.ts`) live in `frontend/src/generated/core/` and `products/{product}/frontend/generated/` — don't edit them manually, change serializers and rerun. See [type system guide](docs/published/handbook/engineering/type-system.md) for the full pipeline
- MCP tools are generated from the same OpenAPI spec — see [implementing MCP tools](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) for the YAML config and codegen workflow
- MCP UI apps (interactive visualizations for tool results) are defined in `products/*/mcp/tools.yaml` under `ui_apps` and auto-generated — see [services/mcp/CONTRIBUTING.md](services/mcp/CONTRIBUTING.md) or use the `implementing-mcp-ui-apps` skill
- When touching a viewset or serializer, ensure schema annotations are present (`@extend_schema` or `@validated_request` on viewset methods, `help_text` on serializer fields) — these flow into generated frontend types and MCP tool schemas
- New features should live in `products/` — read [products/README.md](products/README.md) for layout and setup. When _creating a new_ product, follow [products/architecture.md](products/architecture.md) (DTOs, facades, isolation)
- Always filter querysets by `team_id` — in serializers, access the team via `self.context["get_team"]()`
- **Do not add domain-specific fields to the `Team` model.** Use a Team Extension model instead — see `posthog/models/team/README.md` for the pattern and helpers
- **PostHog event capture in Celery tasks:** Do not use `posthoganalytics.capture()` in Celery tasks — events are silently lost. Use `ph_scoped_capture` from `posthog.ph_client` instead (see its docstring for why and usage).

## Code Style

- Python: Use type hints (mypy-strict style)
- Frontend: TypeScript required, explicit return types
- Frontend: If there is a kea logic file, write all business logic there, avoid React hooks at all costs.
- Imports: Use oxfmt import sorting (automatically runs on format), avoid direct dayjs imports (use lib/dayjs)
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: explain _why_, not _what_ — if the reason isn't important, skip the comment
- Comments: when refactoring or moving code, preserve existing comments unless they are explicitly made obsolete by the change
- Python tests: do not add doc comments
- Python: do not create empty `__init__.py` files
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- Tests: prefer parameterized tests (use the `parameterized` library in Python) — if you're writing multiple assertions for variations of the same logic, it should be parameterized
- Reduce nesting: Use early returns, guard clauses, and helper methods to avoid deeply nested code
- Markdown: prefer semantic line breaks; no hard wrapping
- Use American English spelling
- When mentioning PostHog products, the product names should use Sentence casing, not Title Casing. For example, 'Product analytics', not 'Product Analytics'. Any other buttons, tab text, tooltips, etc should also all use Sentence casing. For example, 'Save as view' instead of 'Save As View'.

## Agent automation

When automating a convention, try these in order — only fall back to the next if the previous isn't suitable:

1. **Linters** (ruff, oxlint, semgrep) — code pattern enforcement, always paired with CI
2. **lint-staged / husky** — file-level validation or warnings at commit time
3. **Skills** (`.agents/skills/`) — scaffold with `hogli init:skill`
4. **AGENTS.md / CLAUDE.md instructions** — when automated enforcement isn't suitable

Claude Code hooks are reserved for environment bootstrapping (`SessionStart` only) — do not add `PreToolUse`, `PostToolUse`, or `Notification` hooks as they add latency and are fragile. Changes to `.claude/hooks/` trigger a lint-staged warning; changes to `.claude/settings.json` are blocked outright.

### Mandatory skill invocation

ALWAYS invoke the matching skill **before** writing or reviewing code in these areas — do not skip, do not attempt the work without loading the skill first.

**Always invoke:**

- `/improving-drf-endpoints` — any DRF viewset or serializer change
- `/django-migrations` — any Django migration
- `/clickhouse-migrations` — any ClickHouse migration
- `/adopting-generated-api-types` — any frontend file using `lib/api`, `api.get<`, `api.create<`, or handwritten API types

**Invoke when in the area:**

- `/implementing-mcp-tools` — adding/modifying endpoints or `tools.yaml`
- `/modifying-taxonomic-filter` — any TaxonomicFilter change
- `/sending-notifications` — adding notification support
- `/writing-skills` — creating or updating skills in `.agents/skills/`
