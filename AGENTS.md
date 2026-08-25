# PostHog Development Guide

## Codebase Structure

- Key entry points: `posthog/api/__init__.py` (API URL routing skeleton; products register their own routes in `products/<name>/backend/routes.py` via `register_routes(routers)`), `posthog/settings/web.py` (Django settings, INSTALLED_APPS), `products/` (product apps)
- [Monorepo layout](docs/internal/monorepo-layout.md) - high-level directory structure (products, services, common, tools)
- [Products README](products/README.md) - how to create and structure products
- [Products architecture](products/architecture.md) - DTOs, facades, isolated testing

## Commands

- Environment:
  - This is a full dev environment, not a restricted patch-editing sandbox — it has `node`, `pnpm`, a package mirror, and `apt`, so tools and dependencies that aren't present yet can be installed, and tests, Storybook, and the app can actually be run. A missing `node_modules`, browser binary, or flox usually just means setup hasn't run yet (`pnpm install`, `npx playwright install --with-deps chromium`, or building the nested `@posthog/quill` workspace that `global.scss` imports), rather than that running things is impossible.
  - So the absence of a tool isn't evidence that a task can't be done — installing it is the first step. The honest signal that something genuinely can't run is an attempt that fails for a specific, nameable reason (no network access, `apt` unavailable, out of memory), which is worth reporting alongside whatever fallback you take.
  - This matters most for visual and UX work, where reading the code isn't the same as seeing the result. Rendering the affected surface (for example in Storybook via a headless browser) and comparing before and after is what actually confirms such a change, and is usually worth the setup cost.
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
  - Frontend: `pnpm --filter=@posthog/frontend fix` (safe Oxlint fixes + Oxfmt; suggestion fixes are not applied). `format` runs Oxfmt only; `lint` and `format:check` only verify.
  - TypeScript check: `pnpm --filter=@posthog/frontend typescript:check`
- Build:
  - Frontend: `pnpm --filter=@posthog/frontend build`
  - Start dev: `./bin/start` or `hogli start` (interactive TUI). Detached mode: `hogli up -d` paired with `hogli wait` / `hogli down`
    - Cloud task VMs (prebaked dev-stack image): run `bootstrap-dev-stack` first (restores compose host aliases, starts dockerd), then `uv sync`, `source .venv/bin/activate`, `hogli start -y -d`, and `hogli wait` (the detached start returns while the stack is still booting; `hogli wait` blocks until every process is ready) — always detached: the sandbox has no TTY, and phrocs under a pseudo-TTY balloons in memory until OOM-killed
    - Cloud task VMs, frontend work: `pnpm install --frozen-lockfile --prefer-offline` links from the prebaked pnpm store, and Playwright Chromium is preinstalled; product/Storybook builds still run from source
- OpenAPI/types: `hogli build:openapi` (regenerate after changing serializers/viewsets)
- LSP: Pyright is configured against the flox venv. Prefer LSP (`goToDefinition`, `findReferences`, `hover`) over grep when navigating or refactoring Python code.
- Dev experience feedback: `hogli devex:feedback "<message>"` sends feedback about repo tooling — hogli, the dev stack, tests, CI, migrations, this setup — straight to the devex team as a `hogli_feedback` event (add `-c bug|idea|praise|question`).
  **Local agents must use it too**: when a hogli command or local dev workflow is broken, slow, or confusing, run it — e.g. `hogli devex:feedback -c bug "migrations:run failed with <error>"`. Do not run it from cloud tasks or agent-server sandboxes; the command is a no-op there.

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
**Shape:** invoke `/writing-pr-descriptions` before writing the body. Lead with the effect a person sees rather than the code path behind it, and hold Changes to that too: a bullet a person can notice says what they now see or do differently, and one line says which part is mechanical. Make the body stand alone for a reader who opens no files, and let its size track the change. Then one fact per bullet, sentences under 25 words, active voice, no idioms. A description that got longer as bullets was not cut.
Always fill the `## 🤖 Agent context` section when creating PRs.
NEVER share sensitive information in a PR description. Users may share sensitive data in an agent session, but those should never surface to a PR description, or comments.

**Screenshots:** Upload frontend/visual changes with `hogli pr:upload-image <file>` and embed the printed markdown. The first run only warns and uploads nothing; re-run with `--yes` to confirm. Only PostHog employees can upload, but the public can permanently view these assets, so only upload the image if you're certain it doesn't contain customer data (including customer names), secrets, or sensitive internal info.

### Rules

- Scope is optional but encouraged when the change is specific to a feature area
- Description should be lowercase and not end with a period
- Keep the first line under 72 characters

### Pushing to remote

Once a branch already has an open PR, push incremental changes and fixes to it without waiting for human guidance — keeping the PR current is part of the work.
Pushes still trigger CI, which burns runner credits, so batch related commits and push once the increment is ready rather than after every change.

A push to this repository cannot be taken back.
Forks, clones, mirrors, and notification emails carry it within seconds, and a later fix commit does not retract what is already in the branch's history — recovering means abandoning the branch and respinning the PR.
That makes the first push of a branch the decision point, not a step you correct afterwards.
So if any part of the work drew on something from your session rather than from this repository — a customer conversation, a support ticket, a log, an internal thread — check what is actually in the diff before that first push.
See [Public open source repo guidance](#public-open-source-repo-guidance) for what has to clear the bar.

#### Forcing the full CI matrix on a draft

Draft PRs run a narrowed matrix.
The `run-ci-backend` and `run-ci-frontend` labels force the full one, but a label alone starts nothing: it takes effect on the next push, or when the PR is marked ready for review.
An empty commit is enough.

```bash
git commit --allow-empty -m "chore(ci): run the full matrix" && git push
```

Do not add `labeled`/`unlabeled` back to a merge gate's `on.pull_request.types` to avoid that push.
GitHub cannot filter a label trigger by name, so every unrelated label re-runs the full matrices against a commit CI has already covered.
Guarding it inside the workflow is worse: skipping the gate job cascades to the `if: always()` aggregator, which counts a skipped dependency as success and posts a green required check with no tests behind it.

#### Stacked PRs

GitHub's native stacked PRs are enabled on this repo — use the `gh stack` CLI and the `/stacking-prs` skill instead of hand-managing branch chains.
A stack lands through the merge queue only after explicit user approval in the current conversation: comment `/trunk merge` on the top layer to enqueue the whole stack (the queue tests and merges it and every unmerged layer below it atomically), or land bottom-first one layer at a time; either way, `gh stack sync --prune` afterwards.
Never `gh stack merge` — it merges the whole chain straight through GitHub's API, so the stack reaches `master` outside the queue.

Restacking force-pushes every branch, and each push triggers a full CI fan-out.
Never restack while any branch in the stack is sitting in the merge queue — the force-push removes it from the queue.
Pushing a deep stack at once can exceed GitHub's per-repo dispatch cap (500 workflow runs / 10s).
The overflow fails as `startup_failure` and takes unrelated runs in the same window down too.
Draft status doesn't help, since runs are dispatched before draft/skip logic applies.

- Keep stacks shallow; merge the base before extending.
- Restack only when you need to, rather than rebasing the whole stack on master repeatedly.
- When a restack must push many branches, stagger them instead of force-pushing all at once.

#### Pre-push checks — merge queue guard

The pre-push hook refuses to push a branch whose PR is sitting in the Trunk merge queue — a push there would knock the PR out of the queue.
A PR whose batch failed and is waiting for a retest does not block, so you can push a fix then — Trunk drops the PR from the queue on push, which is what you want after a failure.
When it blocks you, leave the branch alone and put further changes on a new branch with a new PR; to intentionally update the queued PR instead, run `trunk merge cancel <number>` (or comment `/trunk cancel`), wait for it to leave the queue, then push.
The check fails open (missing `gh` or `trunk`, not logged in, offline, API errors), and `TRUNK_QUEUE_PUSH_CHECK_DISABLED=1` skips it.

#### Pre-push checks — ci:preflight

A pre-push hook runs `hogli ci:preflight --strict`, failing the push on deterministic CI breakage reachable from your diff (lint, lockfiles, migration conflicts). Never bypass it (`--no-verify`).
If it blocks the push, run `hogli ci:preflight --fix`, resolve the remaining `✗ fail` lines, act on the `→ advisory` ones (regenerate OpenAPI types, merge master in), and push again.
In environments without hooks (no `node_modules`), run `hogli ci:preflight --fix` yourself before pushing or reporting a task done. If the command reports it is disabled, that's intentional — proceed.

### Merging PRs

All merges into `master` go through the Trunk merge queue.
Never run `gh pr merge` or click the GitHub merge button — both are blocked by branch ruleset.

Agents must not enqueue, merge, re-enqueue, or otherwise cause a PR to land without explicit user approval in the current conversation for the identified PR or stack. Do not infer that approval from requests to prepare a PR, move it toward merge, make it ready, monitor it, or resolve its blockers. Agents may inspect status, fix code and CI, apply `stamphog` when approval is missing, and report that a PR is ready; then they must wait for a direct instruction to merge or enqueue it.

- After explicit user approval: enqueue with `gh pr comment <number> --body "/trunk merge"`. Cancel: `gh pr comment <number> --body "/trunk cancel"`. Enqueueing a stacked PR also enqueues every unmerged layer below it — comment on the top PR to merge the whole stack. `--no-batch` opts the PR (or stack) out of batching.
- The Trunk CLI is an alternative to the comments: `trunk merge <number>` enqueues, `trunk merge status <number>` inspects, `trunk merge cancel <number>` dequeues. It ships in the flox environment and needs a one-time interactive `trunk login` — run it once even if you prefer the comments, because the same login arms the pre-push merge-queue guard that stops you from knocking a queued PR out of the queue. Agents and headless environments that can't complete the interactive login use the comments.
- Missing required approval: apply the `stamphog` label (`gh pr edit <number> --add-label stamphog`) to trigger the automated review-and-approve flow, and re-apply it whenever it was stripped (`REFUSED`/`ESCALATE` verdict) once the feedback is addressed — re-applying is always safe.
- After enqueueing, babysit the PR until it merges or fails — follow [`.agents/skills/merging-prs/SKILL.md`](./.agents/skills/merging-prs/SKILL.md) for the preflight, watch, and failure-handling loop.
- Queue progress is the `Trunk Merge Queue (master)` check run on the PR's head commit. The PR's own checks don't reflect the queue's testing — it runs CI on a `trunk-merge/**` branch.
- On failure the Trunk bot comments with links to the failing workflows; fix and push if appropriate, then wait for explicit user approval before re-enqueueing.
- Never force-push a branch while it is in the queue — it removes the PR from the queue.

### Public open source repo guidance

This repository is public, and everything you push is public with it: source, tests, fixtures and sample data, comments and docstrings, branch names, commit messages, PR titles, descriptions, and comments, and uploaded screenshots.
Anything you were given as context that is not already in this repository — a customer conversation, a support ticket, a log, an internal thread — has to clear that bar before any of it reaches a file, a message, or a description.

- Never mention internal-only systems, private incidents, customer data, Slack thread contents, unreleased roadmap details, or security-sensitive implementation details. Slack thread links and channel references are fine to include — they sit behind PostHog auth and are useful as origin context — but do not quote or paraphrase what was said in the thread.
- **Derived is not synthetic.** Swapping out names, domains, and identifiers does not make real customer material publishable. The prose, the typos, the error IDs, and the order of events are still theirs, and still disclose what they told us. If you started from real material and edited it, it is derived, however much you changed.
- **Sample data that has to read like the real thing gets invented, not transcribed.** List the properties a case must exercise, then write the case from that list with the real material closed. Use reserved domains (`example.com`), invented identifiers, and obviously fake tokens — customers paste credentials and cookies into support chats, and those must not survive the trip even in fragments.
- **Do not claim a provenance you have not checked.** "Written fresh" in a commit message is a factual claim a reviewer will rely on. If you are unsure, compare your text against the source: any shared run of ~40 characters or more means derived, not fresh.
- Use product-facing and code-facing context that a public OSS contributor could understand from this repository alone.
- If context is sensitive, summarize it at a high level without naming internal tools, accounts, or people.
- Avoid citing private operational scale or incident metrics (for example, exact affected team counts, internal row-volume anecdotes, or customer-specific performance numbers) unless that data is already public and linkable.

Examples:

- ✅ `fix(insights): handle missing series color in trend export`
- ✅ A PR description that links to the originating Slack thread for context
- ✅ A test fixture written from a list of the properties it has to exercise, with the real conversation closed
- ❌ `fix: patch issue found in acme-co prod workspace after sales escalation` — references internal customer
- ❌ `fix: will run fine on our 12 million rows there now` — leaks private operational scale
- ❌ A PR description that quotes verbatim what a coworker said in a Slack thread
- ❌ A test fixture adapted from a real support conversation with the names and domains replaced

## CI / GitHub Actions

- `.nvmrc` controls the Node.js version for all CI workflows (via `actions/setup-node`) — changing it affects every CI job that runs Node
- CI uploads test results to Trunk Flaky Tests; the `trunk` MCP server in `.mcp.json` queries per-test flakiness on a PR or `master` (authenticate via `/mcp`, or a `TRUNK_API_TOKEN` bearer header when headless) — see `/debugging-ci-failures` and `/fixing-flaky-tests`
- Every job in `.github/workflows/` must declare `timeout-minutes` — prevents stuck runners from burning credits indefinitely
- **CI workflow changes must stay backwards compatible with open PRs that haven't rebased.** A workflow edit hits every in-flight PR immediately (it runs against the PR merged with master), but companion changes — a new dependency, file, or config — only reach a branch once it rebases. If the workflow starts requiring something an unrebased branch lacks, every such PR fails before its tests run. Make the new behavior degrade gracefully when the prerequisite is absent, or gate it so unrebased branches are unaffected. This has broken CI repeatedly.

## Security

See [.agents/security.md](.agents/security.md) for security guidelines — least privilege, secrets & service-to-service auth (don't add new `INTERNAL_API_SECRET` callers), SQL, HogQL, and semgrep.

## Architecture guidelines

- **Keep entrypoints thin.** The runtime calls the entrypoint first. Examples: a DRF view, a management command `handle()`, a Celery task body, an HTTP handler, a Rust `main()`, and a React component. An entrypoint reads the input, connects the dependencies, and formats the output. Put all other logic in a function that the entrypoint calls. Call that function directly in a test. If you cannot do this, move the logic out of the entrypoint. If the area already has a place for that logic, use it. Do not make a new one.
- API views should declare request/response schemas — prefer `@validated_request` from `posthog.api.mixins` or `@extend_schema` from drf-spectacular. Plain `ViewSet` methods that validate manually need `@extend_schema(request=YourSerializer)` — without it, drf-spectacular can't discover the request body and generated code gets empty schemas
- Django serializers are the source of truth for frontend API types — `hogli build:openapi` generates TypeScript via drf-spectacular + Orval. Generated files (`api.schemas.ts`, `api.ts`, `api.zod.ts`) live in `frontend/src/generated/core/` and `products/{product}/frontend/generated/` — don't edit them manually, change serializers and rerun. See [type system guide](docs/published/handbook/engineering/type-system.md) for the full pipeline
- MCP tools are generated from the same OpenAPI spec — see [implementing MCP tools](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) for the YAML config and codegen workflow
- MCP UI apps (interactive visualizations for tool results) are defined in `products/*/mcp/tools.yaml` under `ui_apps` and auto-generated — see [services/mcp/CONTRIBUTING.md](services/mcp/CONTRIBUTING.md) or use the `implementing-mcp-ui-apps` skill
- When touching a viewset or serializer, ensure schema annotations are present (`@extend_schema` or `@validated_request` on viewset methods, `help_text` on serializer fields) — these flow into generated frontend types and MCP tool schemas
- New features should live in `products/`. **Create one with `hogli product:bootstrap <name>` — never hand-roll the directory.** The scaffold emits a product that is isolated from its first commit, and `product:lint --all` fails on a new product that is not (see "New products must be isolated" in [products/README.md](products/README.md); [products/architecture.md](products/architecture.md) covers the facade and contract design). Code a single product owns — not just backend/frontend, but scripts, CLIs, services, packages, MCP tools, skills — belongs under `products/<product>/`; reserve top-level `tools/`/`services/`/`packages/`/`cli/` for cross-product things
- **Every tenant-data model must have `team_id`** — either as a FK (`models.ForeignKey("posthog.Team", ...)`) or a plain `BigIntegerField` (for multi-DB products). This is the primary tenant isolation boundary. Models without `team_id` must be org-scoped, user-scoped, or instance-global — never silently unscoped. New models should inherit from `TeamScopedRootMixin` (main DB) or `ProductTeamModel` (separate DB) so they start fail-closed — see `posthog/models/scoping/README.md`. CI enforces this via `posthog/models/scoping/baseline_unmigrated.txt`: any new team-scoped model not on a fail-closed manager fails the IDOR coverage check. In serializers, access the team via `self.context["get_team"]()`. When querying a fail-closed model for one team outside request context (Temporal activities, Celery tasks, management commands), use `Model.objects.for_team(team_id)` — not `Model.all_teams.filter(team_id=...)` or `objects.unscoped().filter(...)`; reserve `all_teams`/`unscoped()` for genuinely cross-team access and Django framework internals. Caveat: `for_team(...).get_or_create(...)`/`.create(...)` still need `team_id` passed explicitly — queryset filters don't propagate into row creation
- **Do not add domain-specific fields to the `Team` model.** Use a Team Extension model instead — see `posthog/models/team/README.md` for the pattern and helpers
- **PostHog event capture in Celery tasks:** Do not use `posthoganalytics.capture()` in Celery tasks — events are silently lost. Use `ph_scoped_capture` from `posthog.ph_client` instead (see its docstring for why and usage).
- **Django admin `ForeignKey` fields need explicit widget config.** When adding a `ForeignKey`/`OneToOneField` to a model that's exposed in Django admin (including via inlines attached to a _related_ admin), list the new field in `autocomplete_fields`, `raw_id_fields`, or `readonly_fields` on **every** admin class that renders the model — otherwise the default `<select>` widget loads the entire target table per row on each change-page render. Prefer declaring the config on a shared base inline so per-parent variants (e.g., subclasses differentiated by `fk_name`) inherit it automatically.
- **Use personhog client for all person/group data access — do not query persons DB tables via the Django ORM or raw SQL.** The `posthog/personhog_client/` gRPC client is the required interface for reading and writing person-related data. This applies to the following tables: `posthog_person`, `posthog_persondistinctid`, `posthog_cohortpeople`, `posthog_group`, `posthog_grouptypemapping`, and related override tables (`posthog_personoverride`, `posthog_pendingpersonoverride`, `posthog_flatpersonoverride`, `posthog_featureflaghashkeyoverride`, `posthog_personlessdistinctid`, `posthog_personoverridemapping`). Use the helpers in `posthog/models/person/util.py` (e.g. `get_person_by_uuid`, `get_persons_by_distinct_ids`, `get_person_by_distinct_id`) and `posthog/models/group_type_mapping.py` (`get_group_types_for_project`) — these already route through personhog with ORM fallback via `_personhog_routed()`. When adding new person/group data access, follow the same `_personhog_routed()` pattern: provide a `personhog_fn` using `get_personhog_client()` and an `orm_fn` fallback. Never add new direct ORM queries like `Person.objects.filter(...)` or `PersonDistinctId.objects.filter(...)` — use the existing routed helpers or create new ones following the established pattern. See `posthog/personhog_client/README.md` for client details and `posthog/personhog_client/client.py` for the full RPC interface.
- **PostHog does not enable `ATOMIC_REQUESTS` — there is no implicit per-request transaction.** Each database operation runs in autocommit mode unless explicitly wrapped. Use `with transaction.atomic():` around the specific writes that must succeed or fail together. Do not wrap an entire view method atomically — keep the block as narrow as possible around the related writes. Avoid performing irreversible side effects (sending emails, calling external APIs, enqueuing Celery tasks) inside an atomic block: if the transaction rolls back, those side effects have already happened. Schedule such side effects after the commit, or use `transaction.on_commit()` for Celery task dispatch.
- **Object storage is SeaweedFS — do not add new MinIO dependencies.** Both S3-compatible stores in the dev/CI stack are SeaweedFS: the `objectstorage` service (S3 API on `:19000`) backs general object storage (`OBJECT_STORAGE_*` settings — exports, media uploads, error-tracking source maps, query cache, tasks), and the `seaweedfs` service (S3 API on `:8333`) backs session replay v2 (`SESSION_RECORDING_V2_S3_*` settings). MinIO now survives only as migration tooling: `docker-compose.hobby.yml` keeps it as a source for `bin/migrate-storage-hobby`, and `bin/upgrade-objectstorage` starts a throwaway MinIO to salvage objects off the pre-swap volume. Outside that, don't add docker-compose services, scripts, tests, or docs that stand up a `minio/minio` container. Code that talks to object storage should go through the existing `OBJECT_STORAGE_*` / `SESSION_RECORDING_V2_S3_*` config and a standard S3 client rather than hardcoding an endpoint — that keeps backends swappable. Note the `objectstorage` service registers its credentials at runtime via a bootstrap loop and returns `InvalidAccessKeyId` until that completes, so anything depending on it must wait for its readiness sentinel rather than just for the container to start.
- **Temporal activity payloads have a ~2 MiB hard limit — pass large data by reference, not by value.** Activity inputs and outputs are serialized across a gRPC boundary that Temporal caps at ~2 MiB per payload (the server rejects larger payloads via `blobSizeLimitError`). As a conservative field-level rule, if a field could exceed ~256 KB once serialized (serialized query results, exported file contents, LLM context, rendered HTML, image bytes, unbounded `list[dict[str, Any]]`), write it to Postgres / S3 / object storage from _inside_ the activity and return only the reference (row ID, S3 key). The workflow already has access to any row ID created earlier in the same run; it does not need the content to flow back through. Shuttling large data through the workflow on the way to persistence is a foreseeable failure mode that produces `PayloadSizeError` (`TMPRL1103`) the moment the underlying data crosses the limit.
- **Outbound calls to a third-party API that need rate-limiting or egress telemetry belong in `posthog/egress/` — add a `<domain>/` incarnation (GitHub is the reference) and route callers through its gated, recorded transport, never hand-rolled `requests`. See `posthog/egress/README.md`.**
- **`services/llm-gateway` is under an unofficial code freeze while callers move to [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway).** New callers and features belong on the Go gateway by default. A Python gateway change needs a documented parity blocker for an active caller and must stay limited to that blocker. Read [`services/llm-gateway/PARITY.md`](services/llm-gateway/PARITY.md). Invoke `/auditing-llm-gateway-parity` for gateway contract changes and parity refreshes, `/finding-llm-gateway-migration-candidates` when deciding what to migrate next, and `/migrating-llm-gateway-callers` when moving a selected caller. The gateway's Postgres role reads only an allowlisted set of tables, with grants maintained in posthog-cloud-infra: a new table read needs the SELECT grant landed there for every environment first, then a declaration in `services/llm-gateway/src/llm_gateway/db/required_tables.py`, which a test binds to the package's SQL. The readiness probe verifies the connected role holds every declared grant on every probe, so a missing grant holds a rollout, and a revoked grant unreadies the running fleet, instead of serving 500s.

## Code Style

- Python: Write as if mypy `--strict` is enabled — annotate all function signatures (arguments + return types), avoid `Any`, use `TYPE_CHECKING` imports for type-only references. When a change is type-risky, run mypy the way CI does — `uv run mypy --cache-fine-grained .`, repo-wide, never a file subset (it follows imports, so a subset misses reverse-dependency breakage); `hogli ci:preflight` reminds you, and CI blocks on the same command. The config isn't fully strict yet, but new code should be
- Python imports: keep imports at module level — not inside functions, methods, or conditionals. Inline imports hide dependencies from static analysis, slow hot paths with repeated lookups, and mask circular-import problems instead of fixing them; ruff's `PLC0415` enforces this. Defer an import only to (1) break a true unavoidable circular import (fix the structure first if you can), (2) reference types under `TYPE_CHECKING`, or (3) keep a heavy/optional dependency off the import path so it loads only when its code runs. For (3), add a justified `# noqa: PLC0415` on the import line (e.g. `# noqa: PLC0415 — keeps the heavy dep off the import path`) — never blanket-suppress the rule
- Python dataclasses: invoke `/writing-dataclasses` before adding or changing a dataclass, returning or passing several values, or passing a dataclass through layers. House decorator is `@frozen` from `posthog.dataclasses`; a bare `@dataclass` without an explicit `frozen=` fails the ratchet in `posthog/test/repo_invariants/test_dataclass_defaults.py`
- Frontend: for any frontend work — the main app (`frontend/src/`) **or** a product frontend (`products/*/frontend/`) — follow [frontend/src/AGENTS.md](frontend/src/AGENTS.md): reuse existing Lemon/quill components instead of hand-rolling tables/badges/labels, import generated `*Api` types instead of handwriting them, and run typecheck/typegen at the right moments. Product frontends share the same components and generated types, so the same rules apply there
- Frontend: TypeScript required, explicit return types
- Frontend: If there is a kea logic file, write all business logic there, avoid React hooks at all costs.
- Frontend (quill design system): before writing UI that imports `@posthog/quill` / `lib/ui/quill`, read [packages/quill/packages/primitives/AGENTS.md](packages/quill/packages/primitives/AGENTS.md) — component choice (dropdown vs select vs combobox, accordion vs collapsible, etc.), composition, and spacing rules. Charts: [packages/quill/packages/charts/AGENTS.md](packages/quill/packages/charts/AGENTS.md); DataTable/DateTimePicker: [packages/quill/packages/components/AGENTS.md](packages/quill/packages/components/AGENTS.md)
- Frontend (quill vs LemonUI): quill is for MCP apps and the desktop app. It is deliberately more compact than LemonUI, so its components look out of place in the main app, and there is no active migration of the main app onto it. In `frontend/src/` and `products/*/frontend/`, use LemonUI, including for menus — `LemonMenu` with a `LemonButton` trigger is the default there. `lib/ui/DropdownMenu` (Radix) is legacy; don't add new ones. Where quill is the right library, don't mix quill and Lemon components within one component's internals, and note that quill uses Base UI's `render` prop rather than Radix's `asChild`, so don't carry `asChild` over when converting
- Frontend: Any button or form submit that triggers a network request must guard against double-submission — disable the button and show a loading state (`loading` / `disabledReason` on `LemonButton`, or equivalent) while the request is in flight. Never leave a submit button clickable during an active mutation; reset the state in both success and error paths. This applies to `<form onSubmit>` handlers, `onClick` handlers that call `api.*`, and any kea `listener` that issues a request — wire the in-flight state (loader `*Loading` selectors, local `useState`, or a reducer) into the trigger's disabled/loading props.
- Imports: Use oxfmt import sorting (automatically runs on format), avoid direct dayjs imports (use lib/dayjs)
- CSS: Use tailwind utility classes instead of inline styles
- Error handling: Prefer explicit error handling with typed errors
- Naming: Use descriptive names, camelCase for JS/TS, snake_case for Python
- Comments: default to short or 1-line comments. Explain _why_, not _what_, and only when a future reader (with no access to this PR or chat) would otherwise be confused
- Comments: use mostly ASD-STE100 Simplified Technical English. Use active voice, simple tenses, one idea per sentence, and consistent terms
- Comments: never log change history or chat context in code — no "previously did X, now does Y", "per <task/PR>", "changed because…", or "AI:"/"agent:" notes. That goes in the commit message and PR description
- Comments: when refactoring or moving code, preserve existing comments unless they are explicitly made obsolete by the change
- Python tests: do not add doc comments
- Python: leave `__init__.py` alone unless a check asks for it. Whether a directory needs one depends on what sits above it. `hogli product:lint` and `posthog/test/repo_invariants/test_pytest_module_collisions.py` say where, and print the fix
- jest tests: when writing jest tests, prefer a single top-level describe block in a file
- Tests: when adding coverage, prefer extending a relevant existing test over creating a new standalone test when practical. Prefer parameterized cases (use the `parameterized` library in Python and `test.each` in Jest) when testing variations of the same behavior
- Tests must earn their place: every new test has to catch a realistic regression no existing test already catches (if you can't name it, don't add it), assert observable behavior through the public interface rather than implementation details, and stay cheap — deterministic, isolated, and at the lowest level that catches the bug (see `/writing-tests`)
- Reduce nesting: Use early returns, guard clauses, and helper methods to avoid deeply nested code
- Markdown: prefer semantic line breaks; no hard wrapping
- Use American English spelling

## User-facing copy

For any text a person reads (UI labels, tooltips, empty/error states, notifications, docs, support replies). Invoke `/writing-user-facing-copy` before writing or editing it — that skill carries the full voice, em-dash, and feature-naming rules. When unsure whether copy reads well, ask a human.

- Sentence case, not Title Case: capitalize only the first word and proper nouns ('Product analytics', 'Save as view').
- Avoid the tells of AI-generated text: em dashes (—), "not just X, but Y", rule-of-three padding, hedging preambles. Write like a person typed it; if you can't tell, ask a human.
- Plain language, no jargon. Use the labels users see, not internal names (`surveyPopupDelaySeconds` becomes "Delay the survey popup").
- Be direct and friendly: short sentences, consistent tone across surfaces.
- Errors and empty states guide, don't dead-end: say what happened and the next action.

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
- `/writing-ui-components` — creating, moving, splitting, or restructuring any component or file under `frontend/src/` or `products/*/frontend/`, extracting or promoting a shared component, or renaming frontend symbols or feature vocabulary
- `/writing-tests` — adding or substantially changing any test (pytest, Jest, or Playwright)
- `/writing-user-facing-copy` — writing or editing any text a user reads (UI labels, tooltips, empty/error states, notifications, docs, support replies), or any code change that adds or changes a visible string
- `/writing-code-comments` — writing or editing a code comment in any language, or reviewing a diff that adds comments
- `/writing-pr-descriptions` — writing or editing any PR body, before `gh pr create` or `gh pr edit --body`

**Invoke when in the area:**

- `/writing-dataclasses` — adding or changing a Python dataclass, replacing a tuple or `dict[str, Any]` payload, or passing a dataclass or facade contract through internal layers
- `/announcing-behavior-changes` — shipping a fix that changes what an existing user sees (a metric moves, a count drops, a range resolves differently), or adding, reviewing, or removing an in-app change notice
- `/merging-prs` — merging a PR, or babysitting one through the Trunk merge queue
- `/stacking-prs` — creating, restacking, adopting, or landing a stack of PRs (`gh stack`)
- `/implementing-mcp-tools` — adding/modifying endpoints or `tools.yaml`
- `/modifying-taxonomic-filter` — any TaxonomicFilter change
- `/placing-product-frontend-code` — adding a frontend file or directory for a product, or deciding between `products/<name>/frontend/` and `frontend/src/scenes/<name>/`
- `/sending-notifications` — adding notification support
- `/writing-skills` — creating or updating skills in `.agents/skills/`
- `/writing-evals` — adding or changing eval suites, cases, scorers, or seeders under `products/posthog_ai/evals/` or `products/*/evals/`, touching the harness in `products/posthog_ai/eval_harness/`, or running those evals
- [`ee/hogai/eval/AGENTS.md`](ee/hogai/eval/AGENTS.md) — writing eval cases or fixture data by hand anywhere (not a skill, and not covered by `/writing-evals`): where that data may come from, and why anonymizing a real conversation does not make it publishable
- `/authoring-ci-workflows` — adding or editing any `.github/workflows` workflow, composite action, or reusable workflow
- `/reviewing-personhog-protocol` — any personhog coordination-protocol change (leases, fencing, handoffs, supervisors, budgets, warming, changelog semantics), and any request for an exhaustive review of personhog code
- `/gating-production-deploys` — any workflow that builds and pushes a production image or dispatches a deploy
- `/splitting-oversized-modules` — splitting a Python module into a package, or deciding whether to propose splitting one before you work in it; propose, and land the move as a stacked base PR rather than inside your feature diff
- `/auditing-llm-gateway-parity` — changing either gateway's auth, attribution, billing, endpoints, providers, models, routing, or metadata contract; reviewing a `services/llm-gateway` change; or refreshing `services/llm-gateway/PARITY.md`
- `/finding-llm-gateway-migration-candidates` — finding, auditing, or ranking callers that could move from `services/llm-gateway` to `PostHog/ai-gateway`, including requests for the next or lowest-risk migration candidate
- `/migrating-llm-gateway-callers` — adding an LLM gateway caller or migrating an existing caller from `services/llm-gateway` to `PostHog/ai-gateway`, including shared client and gateway setting changes made for that migration
