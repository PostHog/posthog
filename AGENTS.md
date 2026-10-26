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
  - Visual and UX work is not confirmed by reading the code. Render the affected surface (the running app, or Storybook via a headless browser) and compare before and after. Worth the setup cost. A story written only for this check is scratch: keep it out of the commit.
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
- Dev experience feedback: `hogli devex:feedback "<message>"` sends feedback about repo tooling — hogli, the dev stack, tests, CI, migrations, this setup — straight to the devex team as a `hogli_feedback` event (add `-c bug|idea|praise|question`).
  **Local agents must use it too**: when a hogli command or local dev workflow is broken, slow, or confusing, run it — e.g. `hogli devex:feedback -c bug "migrations:run failed with <error>"`. Do not run it from cloud tasks or agent-server sandboxes; the command is a no-op there.

## Commits and Pull Requests

- Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages and PR titles.
- When a change touches user-facing behavior, an API, a config/setting, or a documented workflow, update an existing doc under `docs/` **whose scope covers that behavior** in the same PR. If none exists, make no docs change and put PR-specific context in the PR description. `project-structure.md` is a high-level directory map; feature behavior, UI controls, command usage, and worktree notes do not belong there.
- A new `docs/**` file requires a person to request that specific document in the current conversation. Existing related docs, PR checklists, and general docs requirements do not authorize one. Put PR-specific context in the PR description.
- When triaging review bot findings, react to each PostHog Review finding comment (`posthog[bot]`) with 👍 if it is valid or 👎 if not, so review metrics can tell acted-on findings from noise.

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
Always fill the `## 🤖 Agent context` section, including the exact model that wrote the code.
NEVER put sensitive information in a PR description or comment. A user may share sensitive data in an agent session; none of it belongs on the PR.

**Screenshots:** Show frontend/visual changes with a screenshot, or with a feature reel when `/writing-pr-descriptions` calls for one. Upload with `hogli pr:upload-image <file>` and embed the printed markdown. The first run only warns and uploads nothing; re-run with `--yes` to confirm. Only PostHog employees can upload, but the public can permanently view these assets, so only upload the image if you're certain it doesn't contain customer data (including customer names), secrets, or sensitive internal info.

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
Agents may inspect status, fix code and CI, request a stamphog review when a required approval is missing (MCP first, label fallback, see `/merging-prs`), and report that a PR is ready — then wait for a direct instruction.

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

## Read the guide for your area first

Most topic rules live in guides under `.agents/`, not in this file.
Before your first edit, plan, or review finding, open every guide whose area the task touches.
Reviewing a diff counts: the diff touches the areas it changes.

| The task touches                                                                                 | Read first                                                                                            |
| ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| Python or Django backend: models, views, serializers, Celery, Temporal, outbound calls, settings | [.agents/architecture.md](.agents/architecture.md) and [.agents/code-style.md](.agents/code-style.md) |
| Frontend: components, kea logic, buttons, forms                                                  | [.agents/code-style.md](.agents/code-style.md) and [frontend/src/AGENTS.md](frontend/src/AGENTS.md)   |
| A new or changed button, menu item, form, or scene                                               | [.agents/feature-usage-tracking.md](.agents/feature-usage-tracking.md)                                |
| GitHub workflows, `.nvmrc`, publish jobs                                                         | [.agents/ci.md](.agents/ci.md)                                                                        |
| Claude Code hooks, lint-staged, pre-commit, `.claude/settings.json`                              | [.agents/agent-automation.md](.agents/agent-automation.md)                                            |
| Auth, secrets, raw SQL, HogQL string building                                                    | [.agents/security.md](.agents/security.md)                                                            |

## CI / GitHub Actions

Read [.agents/ci.md](.agents/ci.md) before you change a workflow, `.nvmrc`, a publish job, event ingestion, or tests that read event properties, and when you debug flaky CI.

## Security

**Every change lands in `PostHog/posthog`, security fixes included, also when the session starts in a `PostHog/posthog-private` checkout.**
The only exception is a severe vulnerability that team-security agrees needs an embargo, because an embargo pauses the private sync and the merge queue.
Never open anything in `posthog-private` without the user's confirmation in the current conversation.
Hardening, validation, and low-impact access fixes go public with a neutral description.
Read [Routing security fixes](.agents/security.md#routing-security-fixes) before you open a PR for any security fix: it defines "severe" and says what to leave out of a public PR.
The private mirror carries this file, and its `origin` points at the private repo, so a default push or `gh pr create` opens the PR there.
Before the first push of a branch, run `git remote get-url origin`.
If it names `posthog-private` and the change is not an embargoed fix, open the PR from a `PostHog/posthog` checkout.
Do not add new `INTERNAL_API_SECRET` callers.
Read [.agents/security.md](.agents/security.md) before touching auth, secrets, service-to-service calls, raw SQL, or HogQL string building — it covers least privilege, the injection rules, and how to respond when semgrep flags your code.
`.semgrep/rules/security/` is the enforced set; run `semgrep --config .semgrep/rules/security/ .` to check a change locally.

**Treat the Content Security Policy in `CSPMiddleware` as enforced.**
A resource from an origin the policy does not name is refused, and the page shows the user no error, so the feature fails silently.
Loading a script, font, stylesheet, image, frame, or `fetch` target from a new external origin needs that directive widened in the same PR.
`eval` and `new Function` never run, because the policy grants `wasm-unsafe-eval` and nothing more.
In a Django template an inline `<script>` needs `nonce="{{ request.csp_nonce }}"`, and an inline `onclick` or `onsubmit` attribute cannot be made to work at all — put the handler in a nonce'd block instead.
Read [.agents/security.md](.agents/security.md#content-security-policy) for the directive list and the traps before you add any of these.

## Architecture guidelines

Read [.agents/architecture.md](.agents/architecture.md) before you add or change application or dev-stack code: entrypoints, `team_id` scoping, personhog, transactions, API schemas, Celery and Temporal, outbound calls, storage, settings, Django admin, and the `services/llm-gateway` freeze.

## Code Style

Read [.agents/code-style.md](.agents/code-style.md) before you write Python, frontend code, comments, tests, or Markdown, or choose between quill and LemonUI.

## User-facing copy

Invoke `/writing-user-facing-copy` before you write or edit text a person reads. It carries the voice, sentence-case, em-dash, and feature-naming rules. When unsure whether copy reads well, ask a human.

## Feature usage tracking

Read [.agents/feature-usage-tracking.md](.agents/feature-usage-tracking.md) before you add or change a feature a user interacts with, or remove one for low usage.

## Agent automation

Read [.agents/agent-automation.md](.agents/agent-automation.md) before you automate a convention, or change a Claude Code hook, `.claude/settings.json`, a lint-staged task, or a pre-commit check.

## Mandatory skill invocation

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

**Invoke when in the area:**

- `/writing-dataclasses` — adding or changing a Python dataclass, replacing a tuple or `dict[str, Any]` payload, or passing a dataclass or facade contract through internal layers
- `/announcing-behavior-changes` — shipping a fix that changes what an existing user sees (a metric moves, a count drops, a range resolves differently), or adding, reviewing, or removing an in-app change notice
- `/verifying-changes` — choosing how to confirm a change works before reporting it done, or before starting Storybook, the dev stack, or a Playwright run to check your own work
- `/merging-prs` — merging a PR, or babysitting one through the Trunk merge queue
- `/stacking-prs` — creating, restacking, adopting, or landing a stack of PRs (`gh stack`)
- `/implementing-mcp-tools` — adding/modifying endpoints or `tools.yaml`
- `/modifying-taxonomic-filter` — any TaxonomicFilter change
- `/profiling-slow-api-endpoints` — an endpoint, list, picker, or scene is slow, a p95 latency number needs explaining, or a Postgres query plan needs checking against production rather than a local database
- `/placing-product-frontend-code` — adding a frontend file or directory for a product, or deciding between `products/<name>/frontend/` and `frontend/src/scenes/<name>/`
- `/organizing-conversations-code` — adding, moving, renaming, or reviewing files under `products/conversations/`
- `/integrating-with-posthog-ai` — making a product surface work with PostHog AI: injecting scene context or custom instructions, reacting to the agent's tool calls, or rendering your product's tool cards in a thread
- `/sending-notifications` — adding notification support
- `/routing-outbound-api-calls` — adding or changing Python code that calls a third-party HTTP API, or changing any domain under `posthog/egress/` (budget, lanes, identity, metrics, headers)
- `/authenticating-to-clickhouse` — adding a service, sidecar, or container that connects to ClickHouse, adding a `ClickHouseUser`, or building or changing a ClickHouse pool or client by hand; it must stay token-aware (a native pool carries the credential provider, an HTTP client resolves the token per call) or it silently uses the static password
- `/writing-clickhouse-queries` — adding or changing a ClickHouse call site (`sync_execute`, `execute_hogql_query`, a `QueryRunner`), including the `Workload` it passes
- `/adding-activity-logging` — adding activity logging (the audit trail) to a model, writing or changing a `model_activity_signal` receiver or an activity describer, auditing which write paths of a model are logged, or debugging a change that is missing from the activity log
- `/adding-inbound-webhooks` — adding a webhook endpoint for a third party that sends to PostHog, adding a consumer for a provider that already has an endpoint, or migrating a verifier the `inbound-webhooks-go-through-ingress` rule flags
- `/writing-skills` — creating or updating skills in `.agents/skills/`
- `/editing-agents-md` — adding, editing or removing a rule in any `AGENTS.md` or `CLAUDE.md`, root or nested
- `/writing-evals` — adding or changing eval suites, cases, scorers, or seeders under `products/posthog_ai/evals/` or `products/*/evals/`, touching the harness in `products/posthog_ai/eval_harness/`, or running those evals
- [`products/posthog_ai/evals/AGENTS.md`](products/posthog_ai/evals/AGENTS.md) — read before writing eval cases for the seeded Hedgebox taxonomy and the rules for invented case data
- `/authoring-ci-workflows` — adding or editing any `.github/workflows` workflow, composite action, or reusable workflow
- `/reviewing-personhog-protocol` — any personhog coordination-protocol change (leases, fencing, handoffs, supervisors, budgets, warming, changelog semantics), and any request for an exhaustive review of personhog code
- `/gating-production-deploys` — any workflow that builds and pushes a production image or dispatches a deploy
- `/splitting-oversized-modules` — splitting a Python module into a package, or deciding whether to propose splitting one before you work in it, including before you restructure code inside a module over roughly a thousand lines; propose, and land the move as a stacked base PR rather than inside your feature diff
- `/auditing-llm-gateway-parity` — changing either gateway's auth, attribution, billing, endpoints, providers, models, routing, or metadata contract; reviewing a `services/llm-gateway` change; or refreshing `services/llm-gateway/PARITY.md`
- `/finding-llm-gateway-migration-candidates` — finding, auditing, or ranking callers that could move from `services/llm-gateway` to `PostHog/ai-gateway`, including requests for the next or lowest-risk migration candidate
- `/migrating-llm-gateway-callers` — adding an LLM gateway caller or migrating an existing caller from `services/llm-gateway` to `PostHog/ai-gateway`, including shared client and gateway setting changes made for that migration
