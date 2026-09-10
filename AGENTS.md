# PostHog Development Guide

## Codebase Structure

- Key entry points: `posthog/api/__init__.py` (API URL routing skeleton; products register their own routes in `products/<name>/backend/routes.py` via `register_routes(routers)`), `posthog/settings/web.py` (Django settings, INSTALLED_APPS), `products/` (product apps)
- [Monorepo layout](docs/internal/monorepo-layout.md) — read when you need to place a new directory, or to work out which tree owns something (products, services, common, tools)
- [Products README](products/README.md) — read before creating a product or changing one's structure; covers the isolation rules `product:lint` enforces
- [Products architecture](products/architecture.md) — read when designing a product's DTOs, facade, or contract with the rest of the repo
- A directory may carry its own `AGENTS.md` that wins locally (`posthog/temporal/`, `rust/`, `frontend/src/`, most of `products/`). Check for one before working in an unfamiliar tree.

## Commands

- Environment:
  - This is a full dev environment with `node`, `pnpm`, a package mirror and `apt`. A missing `node_modules`, browser binary or flox means setup has not run yet (`pnpm install`, `npx playwright install --with-deps chromium`), not that running things is impossible — install it and continue. Report "can't run" only for a specific, nameable failure (no network, no `apt`, out of memory), alongside whatever fallback you took.
  - Visual and UX work is not confirmed by reading the code. Render the affected surface (Storybook via a headless browser) and compare before and after. Worth the setup cost.
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
    - In a PostHog Tasks cloud run (`POSTHOG_TASK_RUN_ID` set), the boot sequence, prewarmed test database and scoped-test rules differ — read [Cloud task sandbox](docs/internal/cloud-task-sandbox.md) before starting the stack or running tests there
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

**Required:** Read `.github/pull_request_template.md` and use its exact section structure. Do not invent a different format.
Invoke `/writing-pr-descriptions` before writing the body — it carries the shape rules.
Always fill the `## 🤖 Agent context` section.
NEVER put sensitive information in a PR description or comment. A user may share sensitive data in an agent session; none of it belongs on the PR.

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

#### Before you push

- **Never bypass the pre-push hooks** (`--no-verify`). They run `hogli ci:preflight --strict` and a merge-queue guard. When one blocks you, fix what it reports — `/running-ci-preflight` has the loop, `/merging-prs` explains the queue guard.
- **Never force-push a branch that is in the merge queue** — it removes the PR from the queue. That includes restacking a stack whose base is queued.
- Draft PRs run a narrowed CI matrix. To force the full one, see "Forcing the full matrix on a draft" in `/authoring-ci-workflows`.

#### Stacked PRs

GitHub's native stacked PRs are enabled here. Use the `gh stack` CLI and `/stacking-prs` rather than hand-managing branch chains.
Keep stacks shallow and merge the base before extending: restacking force-pushes every branch, and a deep stack pushed at once can exceed GitHub's dispatch cap and fail unrelated runs with it.
Never `gh stack merge` — it lands the chain through GitHub's API, outside the queue.

### Merging PRs

All merges into `master` go through the Trunk merge queue.
Never run `gh pr merge` or click the GitHub merge button — both are blocked by branch ruleset.

**Agents must not enqueue, merge, re-enqueue, or otherwise cause a PR to land without explicit user approval in the current conversation for the identified PR or stack.**
Do not infer that approval from requests to prepare a PR, move it toward merge, make it ready, monitor it, or resolve its blockers.
Agents may inspect status, fix code and CI, apply the `stamphog` label when a required approval is missing, and report that a PR is ready — then wait for a direct instruction.

Once approved, follow `/merging-prs` for the enqueue, watch and failure loop. It also covers why the PR's own checks never show queue progress.

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
- **A workflow edit reaches every open PR before those branches rebase.** It runs against the PR merged with master, but a companion change — a new dependency, file, or config — only arrives when the branch rebases. A workflow that starts requiring something unrebased branches lack fails every in-flight PR before its tests run. Make the new behavior degrade gracefully, or gate it. This has broken CI repeatedly.
- Mechanical workflow rules (`timeout-minutes`, concurrency, dispatch budget, path filters, gate hygiene) are enforced by `hogli lint:workflows` and actionlint, which are the source of truth. `/authoring-ci-workflows` explains the reasoning behind each.

## Security

Do not add new `INTERNAL_API_SECRET` callers.
Read [.agents/security.md](.agents/security.md) before touching auth, secrets, service-to-service calls, raw SQL, or HogQL string building — it covers least privilege, the injection rules, and how to respond when semgrep flags your code.
`.semgrep/rules/security/` is the enforced set; run `semgrep --config .semgrep/rules/security/ .` to check a change locally.

## Architecture guidelines

Each rule is tagged with what catches a violation.
`[lint: <id>]` means a linter, semgrep rule, or invariant test blocks it, so CI is the check and this text is only the reasoning.
`[review]` means nothing catches it automatically — a reader is the only control.

### Entrypoints and layering

- **Keep entrypoints thin.** `[review]` The runtime calls the entrypoint first: a DRF view, a management command `handle()`, a Celery task body, an HTTP handler, a Rust `main()`, a React component. An entrypoint reads the input, connects the dependencies, and formats the output. All other logic goes in a function the entrypoint calls, so a test can call it directly. If the area already has a place for that logic, use it rather than making a new one.
- **A product under `products/` is scaffolded, not hand-rolled.** `[lint: hogli product:lint --all]` Create one with `hogli product:bootstrap <name>`, because the scaffold emits a product that is isolated from its first commit. See "New products must be isolated" in [products/README.md](products/README.md) for the isolation rules, and [products/architecture.md](products/architecture.md) for facade and contract design.
- **Code a single product owns belongs under `products/<product>/`** — backend, frontend, scripts, CLIs, services, packages, MCP tools, skills. `[review]` Reserve top-level `tools/`, `services/`, `packages/` and `cli/` for cross-product things. `product:lint` only scans `products/`, so a single-product feature parked in a top-level directory is invisible to it.

### Tenancy and scoping

- **Every tenant-data model must have `team_id`**, as a FK to `posthog.Team` or a plain `BigIntegerField` for multi-DB products. `[lint: idor-lookup-without-team, check-idor-model-coverage.py]` This is the primary tenant isolation boundary. New models inherit `TeamScopedRootMixin` (main DB) or `ProductTeamModel` (separate DB) so they start fail-closed — see [posthog/models/scoping/README.md](posthog/models/scoping/README.md).
- **Classifying a model as unscoped is a review decision, not a checked one.** `[review]` A model without `team_id` must be org-scoped, user-scoped, or instance-global, never silently unscoped. `check-idor-model-coverage.py` only warns when a name lands in `NEEDS_TEAM_ID`, and passes silently for `LEGITIMATELY_UNSCOPED`, so a wrongly exempted tenant model reaches master unless a reader catches it.
- **Reading a fail-closed model outside request context** — Temporal activities, Celery tasks, management commands — uses `Model.objects.for_team(team_id)`. `[review]` Not `Model.all_teams.filter(team_id=...)` and not `objects.unscoped().filter(...)`; those are for genuinely cross-team access and Django internals. In serializers the team comes from `self.context["get_team"]()`. Caveat: `for_team(...).get_or_create(...)` and `.create(...)` still need `team_id` passed explicitly, because a queryset filter does not propagate into row creation.
- **Do not add domain-specific fields to the `Team` model.** `[review]` Use a Team Extension model — see [posthog/models/team/README.md](posthog/models/team/README.md) for the pattern and helpers.

### Person and group data

- **All person/group access goes through the personhog client.** `[review]` Never query these via the Django ORM or raw SQL: `posthog_person`, `posthog_persondistinctid`, `posthog_cohortpeople`, `posthog_group`, `posthog_grouptypemapping`, and the override tables (`posthog_personoverride`, `posthog_pendingpersonoverride`, `posthog_flatpersonoverride`, `posthog_featureflaghashkeyoverride`, `posthog_personlessdistinctid`, `posthog_personoverridemapping`). Use the routed helpers in `posthog/models/person/util.py` and `posthog/models/group_type_mapping.py`. New access follows the same `_personhog_routed()` pattern: a `personhog_fn` using `get_personhog_client()`, plus an `orm_fn` fallback. See [posthog/personhog_client/README.md](posthog/personhog_client/README.md).
- **Personhog answers identity questions only.** `[review]` Use it for resolving distinct IDs, point lookups by person id or UUID, and lifecycle writes. Person properties, list hydration, and search come from ClickHouse (HogQL over `persons`, `ActorsQueryRunner`). Avoid reading `properties` from personhog — the API will stop surfacing it. Single-person lookups that need properties are exempt only while no ClickHouse primitive covers them, never in bulk. See [docs/internal/person-data-access.md](docs/internal/person-data-access.md).

### Transactions and locking

- **There is no implicit per-request transaction** — PostHog does not enable `ATOMIC_REQUESTS`. `[review]` Every operation runs in autocommit unless wrapped. Put `with transaction.atomic():` around the specific writes that must succeed or fail together, never around a whole view method. Keep irreversible side effects out of the block: an email sent or an API called before a rollback has already happened. Schedule them after the commit, or dispatch Celery tasks with `transaction.on_commit()`.
- **Do not use `Team` or `Organization` rows as mutexes.** `[lint: hot-parent-row-select-for-update]` PostgreSQL takes `KEY SHARE` locks on parent rows for foreign-key checks, and `FOR UPDATE` conflicts with them, so an unrelated child-row write can wait behind a transaction holding a hot parent row. Lock the product's `Team<Product>Config` extension row instead, reached through `get_or_create_team_extension` so the row exists first. For a per-team count limit or number allocation, use a unique constraint, a conditional update, or a dedicated allocation row. Otherwise lock the quiet child row, or take a transaction-scoped advisory lock. Lock `Team` or `Organization` only when the transaction updates or deletes that row, and keep it short — no network calls, no input-sized loops. Each exception needs a short `nosemgrep` justification.

### API schemas and generated types

- **API views declare request/response schemas.** `[review]` Prefer `@validated_request` from `posthog.api.mixins`, or `@extend_schema` from drf-spectacular. A plain `ViewSet` method that validates manually needs `@extend_schema(request=YourSerializer)`; without it drf-spectacular cannot discover the request body and generated code gets an empty schema. Serializer fields need `help_text`. These flow into both frontend types and MCP tool schemas.
- **Django serializers are the source of truth for frontend API types.** `[lint: build:openapi CI gate, prefer-codegen-api]` `hogli build:openapi` generates TypeScript via drf-spectacular and Orval into `frontend/src/generated/core/` and `products/{product}/frontend/generated/`. Never hand-edit `api.schemas.ts`, `api.ts` or `api.zod.ts` — change the serializer and regenerate. [Type system guide](docs/published/handbook/engineering/type-system.md) has the full pipeline.
- MCP tools and MCP UI apps are generated from the same OpenAPI spec. `[review]` See [implementing MCP tools](docs/published/handbook/engineering/ai/implementing-mcp-tools.md) covers the YAML config and codegen. MCP UI apps live in `products/*/mcp/tools.yaml` under `ui_apps` — see [services/mcp/CONTRIBUTING.md](services/mcp/CONTRIBUTING.md) or `/implementing-mcp-ui-apps`.

### Async, storage and outbound calls

- **Do not use `posthoganalytics.capture()` in a Celery task** — events are silently lost. `[review]` Use `ph_scoped_capture` from `posthog.ph_client`; its docstring explains why.
- **Temporal activity payloads cap at ~2 MiB — pass large data by reference.** `[review]` Activity inputs and outputs cross a gRPC boundary the server rejects above that (`blobSizeLimitError`). As a field-level rule: if a field could exceed ~256 KB serialized (query results, exported file contents, LLM context, rendered HTML, image bytes, unbounded `list[dict[str, Any]]`), write it to Postgres or object storage from inside the activity and return only the row ID or S3 key. The workflow already has any ID created earlier in the run. Shuttling large data through the workflow produces `PayloadSizeError` (`TMPRL1103`) as soon as the data crosses the limit.
- **A Python `requests` call to GitHub or Slack under `common/`, `ee/`, `posthog/` or `products/` goes through `posthog/egress/`.** `[lint: github-api-calls-go-through-egress, slack-api-calls-go-through-egress]` Route it through the gated, recorded transport.
- **Every other call to those hosts is on review.** `[review]` The rules match an inline URL in a Python `requests` call inside those four directories. A URL bound to a variable first, another transport such as `httpx`, another language, or a caller under `tools/` all pass CI.
- **Any other third-party API that needs rate-limiting or egress telemetry belongs there too.** `[review]` Add a `<domain>/` incarnation (GitHub is the reference). No semgrep rule covers a new domain, so a raw client for one reaches master unless a reader catches it. See [posthog/egress/README.md](posthog/egress/README.md).
- **Object storage is SeaweedFS — do not add new MinIO dependencies.** `[review]` Both S3-compatible stores are SeaweedFS: `objectstorage` (`:19000`, `OBJECT_STORAGE_*`) for general storage, `seaweedfs` (`:8333`, `SESSION_RECORDING_V2_S3_*`) for session replay v2. MinIO survives only as migration tooling in `docker-compose.hobby.yml` and `bin/upgrade-objectstorage`. Do not add compose services, scripts, tests or docs that stand up a `minio/minio` container. Talk to storage through the existing config and a standard S3 client, never a hardcoded endpoint. Note `objectstorage` registers credentials at runtime and returns `InvalidAccessKeyId` until that finishes, so wait for its readiness sentinel rather than the container start.

### Django admin

- **A new `ForeignKey`/`OneToOneField` on an admin-exposed model needs explicit widget config.** `[review]` List the field in `autocomplete_fields`, `raw_id_fields`, or `readonly_fields` on **every** admin class that renders the model, including inlines attached to a related admin. Otherwise the default `<select>` loads the entire target table per row on each change-page render. Declare it on a shared base inline so per-parent variants inherit it.

### LLM gateway

- **`services/llm-gateway` is under an unofficial code freeze** while callers move to [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway). `[review]` New callers and features belong on the Go gateway. A Python gateway change needs a documented parity blocker for an active caller and stays limited to it — read [`services/llm-gateway/PARITY.md`](services/llm-gateway/PARITY.md). Its Postgres role reads only allowlisted tables: a new table read needs the SELECT grant landed in posthog-cloud-infra for every environment first, then a declaration in `required_tables.py`. The readiness probe checks every declared grant on every probe, so a missing grant holds a rollout instead of serving 500s. Use `/auditing-llm-gateway-parity` for contract changes, `/finding-llm-gateway-migration-candidates` to pick the next caller, `/migrating-llm-gateway-callers` to move one.

## Code Style

Same tags as above: `[lint: <id>]` is machine-enforced, `[review]` is not.

### Python

- **Write as if mypy `--strict` were on.** `[review]` Annotate every signature, avoid `Any`, put type-only references under `TYPE_CHECKING`. The config is not fully strict yet; new code should be. When a change is type-risky run mypy the way CI does — `uv run mypy --cache-fine-grained .`, repo-wide, never a file subset. It follows imports, so a subset misses reverse-dependency breakage.
- **Imports stay at module level.** `[review]` ruff's `PLC0415` catches this, but `posthog/**`, `ee/**`, `common/**`, `tools/**` and most of `products/` are on grandfathered exemption lists, so CI does not block it in the trees you are most likely to be editing. Defer one only to break a true unavoidable circular import, to reference types under `TYPE_CHECKING`, or to keep a heavy or optional dependency off the import path. For the last case add a justified `# noqa: PLC0415 — keeps the heavy dep off the import path` on the line. Never blanket-suppress the rule.
- **A stdlib `@dataclass` must declare `frozen=` explicitly.** `[lint: prefer-frozen-dataclasses, test_dataclass_defaults.py]` A bare `@dataclass` fails the ratchet; `@dataclass(frozen=False)` passes it, so intentional mutability is a choice you state.
- **The house decorator is `@frozen` from `posthog.dataclasses`.** `[review]` Neither check prefers it over a declared stdlib `@dataclass`. Invoke `/writing-dataclasses` before adding or changing one, before returning or passing several values together, and before passing a dataclass through layers.
- **`product:lint` and the pytest collision test say where an `__init__.py` is required, and print the fix.** `[lint: product:lint, test_pytest_module_collisions.py]` Run them rather than reasoning about it.
- **Do not add or delete an `__init__.py` speculatively.** `[review]` Whether a directory needs one depends on what sits above it. Neither check objects to a needless one outside `products/` that creates no module-name collision, so only a reader catches that.
- Prefer classes over loose functions unless a class genuinely does not fit. `[review]` Use `pathlib` over `os.path`. Order functions and methods so a definition appears before its first call.

### Frontend

- **Follow [frontend/src/AGENTS.md](frontend/src/AGENTS.md) for all frontend work** — the main app and `products/*/frontend/` alike, since they share components and generated types. `[review]` It covers reusing Lemon/quill components instead of hand-rolling tables, badges and labels, importing generated `*Api` types instead of handwriting them, and when to run typecheck and typegen.
- **TypeScript with explicit return types. Business logic goes in the kea logic file, not a React hook.** `[review]`
- **Guard every network-triggering button against double submission.** `[review]` Disable it and show a loading state (`loading` / `disabledReason` on `LemonButton`, or equivalent) while the request is in flight, and reset in both the success and error paths. Applies to `<form onSubmit>`, any `onClick` that calls `api.*`, and any kea `listener` that issues a request. Wire in the in-flight state from a loader `*Loading` selector, a reducer, or local `useState`.
- **Every surface must hold up narrow.** `[review]` The nav sidebar plus an open side panel leave a 1280px window about 520px of scene. Break on container queries, not `md:`/`lg:`/`xl:`. Wrap or truncate rather than clip, and stack halves that no longer fit. Render at a few widths before calling it done. We do not support mobile — no phone-width layouts, no touch-sized targets. See "Rule 6" in [frontend/src/AGENTS.md](frontend/src/AGENTS.md).
- **quill is for MCP apps and the desktop app; LemonUI is for everything else.** `[review]` quill is deliberately more compact, so it looks out of place in the main app, and there is no migration of the main app onto it. In `frontend/src/` and `products/*/frontend/` use LemonUI, including menus — `LemonMenu` with a `LemonButton` trigger. `lib/ui/DropdownMenu` (Radix) is legacy; do not add new ones. Where quill is right, do not mix the two inside one component, and remember quill uses Base UI's `render` prop, not Radix's `asChild`. Read [primitives/AGENTS.md](packages/quill/packages/primitives/AGENTS.md) before importing quill — it covers component choice and spacing. Charts: [/working-with-charts](.agents/skills/working-with-charts/SKILL.md) for consumers, [charts/AGENTS.md](packages/quill/packages/charts/AGENTS.md) for library changes. DataTable and DateTimePicker: [components/AGENTS.md](packages/quill/packages/components/AGENTS.md).
- Use tailwind utility classes over inline styles, and `lib/dayjs` over a direct dayjs import. `[review]` oxlint warns on a `style` prop through `react/forbid-dom-props`, but a warning does not block.

### Comments

- **Explain _why_, not _what_,** and only where a future reader with no access to this PR or chat would otherwise be confused. `[review]` Default to one line. Python tests get no doc comments.
- **Never log change history or chat context in code.** `[review]` No "previously did X, now does Y", no "per <task/PR>", no "changed because…", no "AI:" or "agent:" notes. That belongs in the commit message and PR description.
- **When refactoring or moving code, keep the existing comments** unless the change actually makes them obsolete. `[review]`
- Use ASD-STE100 Simplified Technical English: active voice, simple tenses, one idea per sentence, consistent terms. `[review]`

### Tests

- **Every new test must catch a realistic regression no existing test catches.** `[review]` If you cannot name that regression, do not add the test. Assert observable behavior through the public interface, not implementation details, and keep it cheap — deterministic, isolated, at the lowest level that catches the bug. See `/writing-tests`.
- **Extend a relevant existing test rather than adding a standalone one** where practical, and parameterize variations of the same behavior (`parameterized` in Python, `test.each` in Jest). `[review]`
- Jest: one top-level `describe` per file. `[review]` Node.js Jest: `.test.ts` by default, `.serial.test.ts` only when shared mutable infrastructure cannot be isolated (a test that resets a shared database).

### Markdown and prose

- Semantic line breaks, no hard wrapping. American English spelling. `[review]`

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

Claude Code hooks are reserved for environment bootstrapping (`SessionStart` only) — do not add `PreToolUse`, `PostToolUse`, or `Notification` hooks as they add latency and are fragile.
Changes to `.claude/hooks/` trigger a warning from the `pre-commit` hook; changes to `.claude/settings.json` are blocked outright by lint-staged.
A warn-only check belongs in the `pre-commit` hook body rather than in a lint-staged task, because lint-staged discards the output of every task that exits 0.

### Mandatory skill invocation

Each entry below is a trigger, not a task list: it fires on what the diff contains, whether you are writing that code or reading someone else's.
ALWAYS invoke the matching skill **first** — do not skip it, and do not attempt the work or the review without loading it.

**Always invoke:**

- `/improving-drf-endpoints` — any DRF viewset or serializer change
- `/django-migrations` — any Django migration, including deleting a model, table, column, or whole product/app (even when no migration file is written, e.g. removing a product folder)
- `/clickhouse-migrations` — any ClickHouse migration
- `/adopting-generated-api-types` — any frontend file using `lib/api`, `api.get<`, `api.create<`, or handwritten API types
- `/writing-ui-components` — creating, moving, splitting, or restructuring any component or file under `frontend/src/` or `products/*/frontend/`, extracting or promoting a shared component, or renaming frontend symbols or feature vocabulary
- `/working-with-charts`: adding or editing a consumer of `@posthog/quill-charts`. For changes inside the library, follow its package guide instead.
- `/writing-tests` — any change to what a test asserts or sets up (pytest, Jest, or Playwright), down to one fixture or one assertion added to an existing block; renames, formatting, and import sorts are exempt
- `/writing-user-facing-copy` — writing or editing any text a user reads (UI labels, tooltips, empty/error states, notifications, docs, support replies), or any code change that adds or changes a visible string
- `/writing-code-comments` — writing or editing a code comment in any language, or reviewing a diff that adds comments
- `/writing-pr-descriptions` — writing or editing any PR body, before `gh pr create` or `gh pr edit --body`
- `/reviewing-with-coderabbit` — before `gh pr create`, and whenever a review of a branch is asked for; when the CLI is unavailable the PR opens without a local pass, never with `/code-review` or review subagents in its place

**Invoke when in the area:**

- `/writing-dataclasses` — adding or changing a Python dataclass, replacing a tuple or `dict[str, Any]` payload, or passing a dataclass or facade contract through internal layers
- `/announcing-behavior-changes` — shipping a fix that changes what an existing user sees (a metric moves, a count drops, a range resolves differently), or adding, reviewing, or removing an in-app change notice
- `/merging-prs` — merging a PR, or babysitting one through the Trunk merge queue
- `/stacking-prs` — creating, restacking, adopting, or landing a stack of PRs (`gh stack`)
- `/implementing-mcp-tools` — adding/modifying endpoints or `tools.yaml`
- `/modifying-taxonomic-filter` — any TaxonomicFilter change
- `/profiling-slow-api-endpoints` — an endpoint, list, picker, or scene is slow, a p95 latency number needs explaining, or a Postgres query plan needs checking against production rather than a local database
- `/placing-product-frontend-code` — adding a frontend file or directory for a product, or deciding between `products/<name>/frontend/` and `frontend/src/scenes/<name>/`
- [`products/conversations/skills/organizing-conversations-code/SKILL.md`](products/conversations/skills/organizing-conversations-code/SKILL.md) — adding, moving, renaming, or reviewing files under `products/conversations/`
- `/integrating-with-posthog-ai` — making a product surface work with PostHog AI: injecting scene context or custom instructions, reacting to the agent's tool calls, or rendering your product's tool cards in a thread
- `/sending-notifications` — adding notification support
- `/adding-activity-logging` — adding activity logging (the audit trail) to a model, writing or changing a `model_activity_signal` receiver or an activity describer, auditing which write paths of a model are logged, or debugging a change that is missing from the activity log
- `/writing-skills` — creating or updating skills in `.agents/skills/`
- `/editing-agents-md` — adding, editing or removing a rule in any `AGENTS.md` or `CLAUDE.md`, root or nested
- `/writing-evals` — adding or changing eval suites, cases, scorers, or seeders under `products/posthog_ai/evals/` or `products/*/evals/`, touching the harness in `products/posthog_ai/eval_harness/`, or running those evals
- [`ee/hogai/eval/AGENTS.md`](ee/hogai/eval/AGENTS.md) — writing eval cases or fixture data by hand anywhere (not a skill, and not covered by `/writing-evals`): where that data may come from, and why anonymizing a real conversation does not make it publishable
- `/authoring-ci-workflows` — adding or editing any `.github/workflows` workflow, composite action, or reusable workflow
- `/reviewing-personhog-protocol` — any personhog coordination-protocol change (leases, fencing, handoffs, supervisors, budgets, warming, changelog semantics), and any request for an exhaustive review of personhog code
- `/gating-production-deploys` — any workflow that builds and pushes a production image or dispatches a deploy
- `/splitting-oversized-modules` — splitting a Python module into a package, or deciding whether to propose splitting one before you work in it, including before you restructure code inside a module over roughly a thousand lines; propose, and land the move as a stacked base PR rather than inside your feature diff
- `/auditing-llm-gateway-parity` — changing either gateway's auth, attribution, billing, endpoints, providers, models, routing, or metadata contract; reviewing a `services/llm-gateway` change; or refreshing `services/llm-gateway/PARITY.md`
- `/finding-llm-gateway-migration-candidates` — finding, auditing, or ranking callers that could move from `services/llm-gateway` to `PostHog/ai-gateway`, including requests for the next or lowest-risk migration candidate
- `/migrating-llm-gateway-callers` — adding an LLM gateway caller or migrating an existing caller from `services/llm-gateway` to `PostHog/ai-gateway`, including shared client and gateway setting changes made for that migration
