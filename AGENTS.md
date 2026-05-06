# PostHog Development Guide

## Codebase Structure

- Key entry points: `posthog/api/__init__.py` (URL routing), `posthog/settings/web.py` (Django settings, INSTALLED_APPS), `products/` (product apps)
- [Monorepo layout](docs/internal/monorepo-layout.md) - high-level directory structure (products, services, common, tools)
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
  - Frontend: `pnpm --filter=@posthog/frontend format`
  - TypeScript check: `pnpm --filter=@posthog/frontend typescript:check`
- Build:
  - Frontend: `pnpm --filter=@posthog/frontend build`
  - Start dev: `./bin/start` or `hogli start` (interactive TUI). Detached mode: `hogli up -d` paired with `hogli wait` / `hogli down`
- OpenAPI/types: `hogli build:openapi` (regenerate after changing serializers/viewsets)
- New product: `bin/hogli product:bootstrap <name>`
- LSP: Pyright is configured against the flox venv. Prefer LSP (`goToDefinition`, `findReferences`, `hover`) over grep when navigating or refactoring Python code.

## Commits and Pull Requests

- Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages and PR titles.
- Check docs for any content that may need updating, you can find these at `docs/`

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
Always fill the `## 🤖 Agent context` section when creating PRs.
Keep descriptions high-level, focusing on rationale and architecture for the human reviewer.

### Rules

- Scope is optional but encouraged when the change is specific to a feature area
- Description should be lowercase and not end with a period
- Keep the first line under 72 characters

### Pushing to remote

Pushes trigger CI, which burns runner credits. Refrain from pushing unless explicitly instructed or until the task is complete — batch local commits and push once at the end rather than after every change. If you're mid-task or iterating, keep work local.

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
- Django serializers are the source of truth for frontend API types — `hogli build:openapi` generates TypeScript via drf-spectacular + Orval. Generated files (`api.schemas.ts`, `api.ts`, `api.zod.ts`) live in `frontend/src/generated/core/` and `products/{product}/frontend/generated/` — don't edit them manually, change serializers and rerun. See [type system guide](docs/published/handbook/engineering/type-system.md) for the full pipeline
- MCP tools are generated from the same OpenAPI spec — see [implementing MCP tools](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) for the YAML config and codegen workflow
- MCP UI apps (interactive visualizations for tool results) are defined in `products/*/mcp/tools.yaml` under `ui_apps` and auto-generated — see [services/mcp/CONTRIBUTING.md](services/mcp/CONTRIBUTING.md) or use the `implementing-mcp-ui-apps` skill
- When touching a viewset or serializer, ensure schema annotations are present (`@extend_schema` or `@validated_request` on viewset methods, `help_text` on serializer fields) — these flow into generated frontend types and MCP tool schemas
- New features should live in `products/` — read [products/README.md](products/README.md) for layout and setup. When _creating a new_ product, follow [products/architecture.md](products/architecture.md) (DTOs, facades, isolation)
- **Every tenant-data model must have `team_id`** — either as a FK (`models.ForeignKey("posthog.Team", ...)`) or a plain `BigIntegerField` (for multi-DB products). This is the primary tenant isolation boundary. Models without `team_id` must be org-scoped, user-scoped, or instance-global — never silently unscoped. For new products, inherit from `ProductTeamModel` (see `posthog/models/scoping/README.md`). In serializers, access the team via `self.context["get_team"]()`
- **Do not add domain-specific fields to the `Team` model.** Use a Team Extension model instead — see `posthog/models/team/README.md` for the pattern and helpers
- **PostHog event capture in Celery tasks:** Do not use `posthoganalytics.capture()` in Celery tasks — events are silently lost. Use `ph_scoped_capture` from `posthog.ph_client` instead (see its docstring for why and usage).
- **Django admin `ForeignKey` fields need explicit widget config.** When adding a `ForeignKey`/`OneToOneField` to a model that's exposed in Django admin (including via inlines attached to a _related_ admin), list the new field in `autocomplete_fields`, `raw_id_fields`, or `readonly_fields` on **every** admin class that renders the model — otherwise the default `<select>` widget loads the entire target table per row on each change-page render. Prefer declaring the config on a shared base inline so per-parent variants (e.g., subclasses differentiated by `fk_name`) inherit it automatically.
- **Use personhog client for all person/group data access — do not query persons DB tables via the Django ORM or raw SQL.** The `posthog/personhog_client/` gRPC client is the required interface for reading and writing person-related data. This applies to the following tables: `posthog_person`, `posthog_persondistinctid`, `posthog_cohortpeople`, `posthog_group`, `posthog_grouptypemapping`, and related override tables (`posthog_personoverride`, `posthog_pendingpersonoverride`, `posthog_flatpersonoverride`, `posthog_featureflaghashkeyoverride`, `posthog_personlessdistinctid`, `posthog_personoverridemapping`). Use the helpers in `posthog/models/person/util.py` (e.g. `get_person_by_uuid`, `get_persons_by_distinct_ids`, `get_person_by_distinct_id`) and `posthog/models/group_type_mapping.py` (`get_group_types_for_project`) — these already route through personhog with ORM fallback via `_personhog_routed()`. When adding new person/group data access, follow the same `_personhog_routed()` pattern: provide a `personhog_fn` using `get_personhog_client()` and an `orm_fn` fallback. Never add new direct ORM queries like `Person.objects.filter(...)` or `PersonDistinctId.objects.filter(...)` — use the existing routed helpers or create new ones following the established pattern. See `posthog/personhog_client/README.md` for client details and `posthog/personhog_client/client.py` for the full RPC interface.
- **Temporal activity payloads have a ~2 MiB hard limit — pass large data by reference, not by value.** Activity inputs and outputs are serialized across a gRPC boundary that Temporal caps at ~2 MiB per payload (the server rejects larger payloads via `blobSizeLimitError`). As a conservative field-level rule, if a field could exceed ~256 KB once serialized (serialized query results, exported file contents, LLM context, rendered HTML, image bytes, unbounded `list[dict[str, Any]]`), write it to Postgres / S3 / object storage from _inside_ the activity and return only the reference (row ID, S3 key). The workflow already has access to any row ID created earlier in the same run; it does not need the content to flow back through. Shuttling large data through the workflow on the way to persistence is a foreseeable failure mode that produces `PayloadSizeError` (`TMPRL1103`) the moment the underlying data crosses the limit.

## Code Style

- Python: Write as if mypy `--strict` is enabled — annotate all function signatures (arguments + return types), avoid `Any`, use `TYPE_CHECKING` imports for type-only references. Do not run mypy locally (too slow); CI runs it on every PR. The config isn't fully strict yet, but new code should be
- Python imports: Place all imports at the top of the file (module level). Do not put imports inside functions, methods, or conditionals. Inline imports hide dependencies from static analysis, slow down hot paths with repeated lookups, and obscure circular-import problems instead of fixing them. The only acceptable reasons to defer an import are (1) breaking a true unavoidable circular import — fix the structure first if you can, and (2) `TYPE_CHECKING` blocks for type-only references. If you reach for an inline import to dodge an import-time side effect or startup cost, fix the offending module instead
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
