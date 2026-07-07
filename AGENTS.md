# PostHog Development Guide

## General guidelines

- Avoid em-dashes like the plague

## Codebase Structure

- Key entry points: `posthog/api/__init__.py` (API URL routing skeleton; products register their own routes in `products/<name>/backend/routes.py` via `register_routes(routers)`), `posthog/settings/web.py` (Django settings, INSTALLED_APPS), `products/` (product apps)
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
- Dev experience feedback: `hogli devex:feedback "<message>"` sends feedback about repo tooling — hogli, the dev stack, tests, CI, migrations, this setup — straight to the devex team as a `hogli_feedback` event (add `-c bug|idea|praise|question`).
  **Agents must use it too**: when a hogli command or dev workflow is broken, slow, or confusing, run it — e.g. `hogli devex:feedback -c bug "migrations:run failed with <error>"`. Agent-sent feedback is tagged as such, and it's the fastest signal the devex team gets, so use it liberally rather than suffering friction silently.

## Commits and Pull Requests

- Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages and PR titles.
- When a change touches user-facing behavior, an API, a config/setting, or a documented workflow, update the matching doc under `docs/` **in the same PR** — treat a stale doc as part of the breakage, not a follow-up.

### Commit types

- `feat`: New feature or functionality (touches production code)
- `fix`: Bug fix (touches production code)
- `chore`: Non-production changes (docs, tests, config, CI, refactoring agents instructions, etc.)
- Scope convention: use `aio` for AI observability changes (for example, `feat(aio): ...`)

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
NEVER share sensitive information in a PR description. Users may share sensitive data in an agent session, but those should never surface to a PR description, or comments.

### Rules

- Scope is optional but encouraged when the change is specific to a feature area
- Description should be lowercase and not end with a period
- Keep the first line under 72 characters

### Pushing to remote

Once a branch already has an open PR, push incremental changes and fixes to it without waiting for human guidance — keeping the PR current is part of the work.
Pushes still trigger CI, which burns runner credits, so batch related commits and push once the increment is ready rather than after every change.

#### Stacked PRs

Restacking force-pushes every branch, and each push triggers a full CI fan-out.
Pushing a deep stack at once can exceed GitHub's per-repo dispatch cap (500 workflow runs / 10s).
The overflow fails as `startup_failure` and takes unrelated runs in the same window down too.
Draft status doesn't help, since runs are dispatched before draft/skip logic applies.

- Keep stacks shallow; merge the base before extending.
- Restack only when you need to, rather than rebasing the whole stack on master repeatedly.
- When a restack must push many branches, stagger them instead of force-pushing all at once.

#### Pre-push checks — ci:preflight

A pre-push hook runs `hogli ci:preflight --strict`, failing the push on deterministic CI breakage reachable from your diff (lint, lockfiles, migration conflicts). Never bypass it (`--no-verify`).
If it blocks the push, run `hogli ci:preflight --fix`, resolve the remaining `✗ fail` lines, act on the `→ advisory` ones (regenerate OpenAPI types, merge master in), and push again.
In environments without hooks (no `node_modules`), run `hogli ci:preflight --fix` yourself before pushing or reporting a task done. If the command reports it is disabled, that's intentional — proceed.

### Public open source repo guidance

This repository is public and all commit messages, pull request titles, and pull request descriptions must be safe for public readers.

- Never mention internal-only systems, private incidents, customer data, Slack thread contents, unreleased roadmap details, or security-sensitive implementation details. Slack thread links and channel references are fine to include — they sit behind PostHog auth and are useful as origin context — but do not quote or paraphrase what was said in the thread.
- Use product-facing and code-facing context that a public OSS contributor could understand from this repository alone.
- If context is sensitive, summarize it at a high level without naming internal tools, accounts, or people.
- Avoid citing private operational scale or incident metrics (for example, exact affected team counts, internal row-volume anecdotes, or customer-specific performance numbers) unless that data is already public and linkable.

Examples:

- ✅ `fix(insights): handle missing series color in trend export`
- ✅ A PR description that links to the originating Slack thread for context
- ❌ `fix: patch issue found in acme-co prod workspace after sales escalation` — references internal customer
- ❌ `fix: will run fine on our 12 million rows there now` — leaks private operational scale
- ❌ A PR description that quotes verbatim what a coworker said in a Slack thread

## CI / GitHub Actions

- `.nvmrc` controls the Node.js version for all CI workflows (via `actions/setup-node`) — changing it affects every CI job that runs Node
- Every job in `.github/workflows/` must declare `timeout-minutes` — prevents stuck runners from burning credits indefinitely
- **CI workflow changes must stay backwards compatible with open PRs that haven't rebased.** A workflow edit hits every in-flight PR immediately (it runs against the PR merged with master), but companion changes — a new dependency, file, or config — only reach a branch once it rebases. If the workflow starts requiring something an unrebased branch lacks, every such PR fails before its tests run. Make the new behavior degrade gracefully when the prerequisite is absent, or gate it so unrebased branches are unaffected. This has broken CI repeatedly.

## Security

See [.agents/security.md](.agents/security.md) for security guidelines — least privilege, secrets & service-to-service auth (don't add new `INTERNAL_API_SECRET` callers), SQL, HogQL, and semgrep.

## Architecture guidelines

- API views should declare request/response schemas — prefer `@validated_request` from `posthog.api.mixins` or `@extend_schema` from drf-spectacular. Plain `ViewSet` methods that validate manually need `@extend_schema(request=YourSerializer)` — without it, drf-spectacular can't discover the request body and generated code gets empty schemas
- Django serializers are the source of truth for frontend API types — `hogli build:openapi` generates TypeScript via drf-spectacular + Orval. Generated files (`api.schemas.ts`, `api.ts`, `api.zod.ts`) live in `frontend/src/generated/core/` and `products/{product}/frontend/generated/` — don't edit them manually, change serializers and rerun. See [type system guide](docs/published/handbook/engineering/type-system.md) for the full pipeline
- MCP tools are generated from the same OpenAPI spec — see [implementing MCP tools](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) for the YAML config and codegen workflow
- MCP UI apps (interactive visualizations for tool results) are defined in `products/*/mcp/tools.yaml` under `ui_apps` and auto-generated — see [services/mcp/CONTRIBUTING.md](services/mcp/CONTRIBUTING.md) or use the `implementing-mcp-ui-apps` skill
- When touching a viewset or serializer, ensure schema annotations are present (`@extend_schema` or `@validated_request` on viewset methods, `help_text` on serializer fields) — these flow into generated frontend types and MCP tool schemas
- New features should live in `products/` — read [products/README.md](products/README.md) for layout and setup. When _creating a new_ product, follow [products/architecture.md](products/architecture.md) (DTOs, facades, isolation). Code a single product owns — not just backend/frontend, but scripts, CLIs, services, packages, MCP tools, skills — belongs under `products/<product>/`; reserve top-level `tools/`/`services/`/`packages/`/`cli/` for cross-product things
- **Every tenant-data model must have `team_id`** — either as a FK (`models.ForeignKey("posthog.Team", ...)`) or a plain `BigIntegerField` (for multi-DB products). This is the primary tenant isolation boundary. Models without `team_id` must be org-scoped, user-scoped, or instance-global — never silently unscoped. New models should inherit from `TeamScopedRootMixin` (main DB) or `ProductTeamModel` (separate DB) so they start fail-closed — see `posthog/models/scoping/README.md`. CI enforces this via `posthog/models/scoping/baseline_unmigrated.txt`: any new team-scoped model not on a fail-closed manager fails the IDOR coverage check. In serializers, access the team via `self.context["get_team"]()`. When querying a fail-closed model for one team outside request context (Temporal activities, Celery tasks, management commands), use `Model.objects.for_team(team_id)` — not `Model.all_teams.filter(team_id=...)` or `objects.unscoped().filter(...)`; reserve `all_teams`/`unscoped()` for genuinely cross-team access and Django framework internals. Caveat: `for_team(...).get_or_create(...)`/`.create(...)` still need `team_id` passed explicitly — queryset filters don't propagate into row creation
- **Do not add domain-specific fields to the `Team` model.** Use a Team Extension model instead — see `posthog/models/team/README.md` for the pattern and helpers
- **PostHog event capture in Celery tasks:** Do not use `posthoganalytics.capture()` in Celery tasks — events are silently lost. Use `ph_scoped_capture` from `posthog.ph_client` instead (see its docstring for why and usage).
- **Django admin `ForeignKey` fields need explicit widget config.** When adding a `ForeignKey`/`OneToOneField` to a model that's exposed in Django admin (including via inlines attached to a _related_ admin), list the new field in `autocomplete_fields`, `raw_id_fields`, or `readonly_fields` on **every** admin class that renders the model — otherwise the default `<select>` widget loads the entire target table per row on each change-page render. Prefer declaring the config on a shared base inline so per-parent variants (e.g., subclasses differentiated by `fk_name`) inherit it automatically.
- **Use personhog client for all person/group data access — do not query persons DB tables via the Django ORM or raw SQL.** The `posthog/personhog_client/` gRPC client is the required interface for reading and writing person-related data. This applies to the following tables: `posthog_person`, `posthog_persondistinctid`, `posthog_cohortpeople`, `posthog_group`, `posthog_grouptypemapping`, and related override tables (`posthog_personoverride`, `posthog_pendingpersonoverride`, `posthog_flatpersonoverride`, `posthog_featureflaghashkeyoverride`, `posthog_personlessdistinctid`, `posthog_personoverridemapping`). Use the helpers in `posthog/models/person/util.py` (e.g. `get_person_by_uuid`, `get_persons_by_distinct_ids`, `get_person_by_distinct_id`) and `posthog/models/group_type_mapping.py` (`get_group_types_for_project`) — these already route through personhog with ORM fallback via `_personhog_routed()`. When adding new person/group data access, follow the same `_personhog_routed()` pattern: provide a `personhog_fn` using `get_personhog_client()` and an `orm_fn` fallback. Never add new direct ORM queries like `Person.objects.filter(...)` or `PersonDistinctId.objects.filter(...)` — use the existing routed helpers or create new ones following the established pattern. See `posthog/personhog_client/README.md` for client details and `posthog/personhog_client/client.py` for the full RPC interface.
- **PostHog does not enable `ATOMIC_REQUESTS` — there is no implicit per-request transaction.** Each database operation runs in autocommit mode unless explicitly wrapped. Use `with transaction.atomic():` around the specific writes that must succeed or fail together. Do not wrap an entire view method atomically — keep the block as narrow as possible around the related writes. Avoid performing irreversible side effects (sending emails, calling external APIs, enqueuing Celery tasks) inside an atomic block: if the transaction rolls back, those side effects have already happened. Schedule such side effects after the commit, or use `transaction.on_commit()` for Celery task dispatch.
- **Prefer SeaweedFS over MinIO for object storage — we are working to remove MinIO from the stack.** SeaweedFS (the `seaweedfs` service, S3 API on `:8333`) is the direction of travel for S3-compatible object storage and already backs session replay v2 (`SESSION_RECORDING_V2_S3_*` settings, default endpoint `http://seaweedfs:8333`). MinIO (the `objectstorage` service, S3 API on `:19000`) still backs general object storage (`OBJECT_STORAGE_*` settings — exports, media uploads, error-tracking source maps, query cache, tasks), but it is being phased out. Do not introduce new dependencies on MinIO: don't add new docker-compose services, scripts, tests, or docs that stand up a `minio/minio` container or hardcode `objectstorage:19000`. Both stores are S3-compatible, so code that talks to object storage should go through the existing `OBJECT_STORAGE_*` / `SESSION_RECORDING_V2_S3_*` config and a standard S3 client rather than hardcoding an endpoint — that keeps backends swappable as MinIO is retired. When a new local-dev feature needs an S3-compatible store, point it at SeaweedFS.
- **Temporal activity payloads have a ~2 MiB hard limit — pass large data by reference, not by value.** Activity inputs and outputs are serialized across a gRPC boundary that Temporal caps at ~2 MiB per payload (the server rejects larger payloads via `blobSizeLimitError`). As a conservative field-level rule, if a field could exceed ~256 KB once serialized (serialized query results, exported file contents, LLM context, rendered HTML, image bytes, unbounded `list[dict[str, Any]]`), write it to Postgres / S3 / object storage from _inside_ the activity and return only the reference (row ID, S3 key). The workflow already has access to any row ID created earlier in the same run; it does not need the content to flow back through. Shuttling large data through the workflow on the way to persistence is a foreseeable failure mode that produces `PayloadSizeError` (`TMPRL1103`) the moment the underlying data crosses the limit.
- **Outbound calls to a third-party API that need rate-limiting or egress telemetry belong in `posthog/egress/` — add a `<domain>/` incarnation (GitHub is the reference) and route callers through its gated, recorded transport, never hand-rolled `requests`. See `posthog/egress/README.md`.**

## Code Style

- Python: Write as if mypy `--strict` is enabled — annotate all function signatures (arguments + return types), avoid `Any`, use `TYPE_CHECKING` imports for type-only references. Do not run mypy locally (too slow); CI runs it on every PR. The config isn't fully strict yet, but new code should be
- Python imports: keep imports at module level — not inside functions, methods, or conditionals. Inline imports hide dependencies from static analysis, slow hot paths with repeated lookups, and mask circular-import problems instead of fixing them; ruff's `PLC0415` enforces this. Defer an import only to (1) break a true unavoidable circular import (fix the structure first if you can), (2) reference types under `TYPE_CHECKING`, or (3) keep a heavy/optional dependency off the import path so it loads only when its code runs. For (3), add a justified `# noqa: PLC0415` on the import line (e.g. `# noqa: PLC0415 — keeps the heavy dep off the import path`) — never blanket-suppress the rule
- Frontend: for any frontend work — the main app (`frontend/src/`) **or** a product frontend (`products/*/frontend/`) — follow [frontend/src/AGENTS.md](frontend/src/AGENTS.md): reuse existing Lemon/quill components instead of hand-rolling tables/badges/labels, import generated `*Api` types instead of handwriting them, and run typecheck/typegen at the right moments. Product frontends share the same components and generated types, so the same rules apply there
- Frontend: TypeScript required, explicit return types
- Frontend: If there is a kea logic file, write all business logic there, avoid React hooks at all costs.
- Frontend (quill design system): before writing UI that imports `@posthog/quill` / `lib/ui/quill`, read [packages/quill/packages/primitives/AGENTS.md](packages/quill/packages/primitives/AGENTS.md) — component choice (dropdown vs select vs combobox, accordion vs collapsible, etc.), composition, and spacing rules. Charts: [packages/quill/packages/charts/AGENTS.md](packages/quill/packages/charts/AGENTS.md); DataTable/DateTimePicker: [packages/quill/packages/components/AGENTS.md](packages/quill/packages/components/AGENTS.md)
- Frontend (quill vs LemonUI): LemonUI is the default in the main app. Use quill for menus, comboboxes, and autocompletes (`DropdownMenu`, `Combobox`, `Autocomplete` from `@posthog/quill`), with the trigger styled to match the surrounding scene's existing UI (LemonButton / ButtonPrimitive). Don't add new `LemonMenu` or `lib/ui/DropdownMenu` (Radix) menus — those are legacy. Don't mix quill and Lemon components within one component's internals. Quill uses Base UI's `render` prop, not Radix's `asChild` — don't carry `asChild` over when converting
- Frontend: Any button or form submit that triggers a network request must guard against double-submission — disable the button and show a loading state (`loading` / `disabledReason` on `LemonButton`, or equivalent) while the request is in flight. Never leave a submit button clickable during an active mutation; reset the state in both success and error paths. This applies to `<form onSubmit>` handlers, `onClick` handlers that call `api.*`, and any kea `listener` that issues a request — wire the in-flight state (loader `*Loading` selectors, local `useState`, or a reducer) into the trigger's disabled/loading props.
- Imports: Use oxfmt import sorting (automatically runs on format), avoid direct dayjs imports (use lib/dayjs)
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: default to short or 1-line comments. Explain _why_, not _what_, and only when a future reader (with no access to this PR or chat) would otherwise be confused
- Comments: never log change history or chat context in code — no "previously did X, now does Y", "per <task/PR>", "changed because…", or "AI:"/"agent:" notes. That goes in the commit message and PR description
- Comments: when refactoring or moving code, preserve existing comments unless they are explicitly made obsolete by the change
- Python tests: do not add doc comments
- Python: do not create empty `__init__.py` files
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- Tests: prefer parameterized tests (use the `parameterized` library in Python) — if you're writing multiple assertions for variations of the same logic, it should be parameterized
- Tests must earn their place: every new test has to catch a realistic regression no existing test already catches (if you can't name it, don't add it), assert observable behavior through the public interface rather than implementation details, and stay cheap — deterministic, isolated, and at the lowest level that catches the bug (see `/writing-tests`)
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
- `/django-migrations` — any Django migration, including deleting a model, table, column, or whole product/app (even when no migration file is written, e.g. removing a product folder)
- `/clickhouse-migrations` — any ClickHouse migration
- `/adopting-generated-api-types` — any frontend file using `lib/api`, `api.get<`, `api.create<`, or handwritten API types
- `/writing-tests` — adding or substantially changing any test (pytest, Jest, or Playwright)

**Invoke when in the area:**

- `/implementing-mcp-tools` — adding/modifying endpoints or `tools.yaml`
- `/modifying-taxonomic-filter` — any TaxonomicFilter change
- `/sending-notifications` — adding notification support
- `/writing-skills` — creating or updating skills in `.agents/skills/`
- `/gating-production-deploys` — any workflow that builds and pushes a production image or dispatches a deploy
- `/versioning-temporal-workflows` — editing the body of an existing `@workflow.defn` class (activity/child-workflow/timer calls added, removed, or reordered)
