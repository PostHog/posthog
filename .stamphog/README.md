# .stamphog

The PostHog monorepo's own stamphog configuration.

How the hosted product reads this directory: [`products/stamphog/README.md`](../products/stamphog/README.md#customize-the-review-for-your-repository).
What each file contains and how per-folder overrides resolve: [the engine's "Policy files" section](../products/stamphog/packages/pr-approval-agent/README.md#policy-files).

## What this repository configures

`policy.yml` declares only what differs from the shipped default, which the engine merges it onto:

- `infra_cicd` replaces its `paths` list. It also matches `.github/pr-deploy`, and of the workflows it keeps only the ones that CODEOWNERS assigns to `team-security`, so those stay denied for every author.
- `ci_workflows` is an extra, owner-only category. It matches every file under `.github/workflows/` and `.depot/workflows/`, and its `exempt_author_teams` lets stamphog approve there only for authors on `team-devex`.
- `stamphog_policy` extends its paths with `packages/owners-yaml/`, `owners.yaml` and `product.yaml`, because those are gate inputs here.
- `devex_guardrails` is an extra category. It matches the semgrep rules, ratchet baselines, invariant tests and lint code that guard the house patterns, so an edit to a guard always gets a human review.
- `agent_steering` is an extra, owner-only category. It matches the root `AGENTS.md`, the PR template, the `writing-pr-descriptions` skill, `.claude/settings.json`, `.claude/hooks/` and `.mcp.json`, and its `exempt_author_teams` lets stamphog approve there only for authors on `team-devex`.
- `workflows_delivery` is an extra, owner-only category. It matches the CDP, Workflows and Messaging API, models and plugin-server worker code, and its `exempt_author_teams` lets stamphog approve there only for authors on `team-workflows`.
- `deny_exceptions` lifts `auth` and `billing` for `products/warehouse_sources/backend/temporal/data_imports/sources/`, because connector code does OAuth and talks to the Stripe API without touching PostHog's auth system or its billing. It lifts `workflows_delivery` for the CDP and Messaging API test directories.
- `allow` extends its path patterns with `.github/CODEOWNERS`.

The repository uses the shipped default `review-guidance.md`.

`steering.md` tells the reviewer to refuse a diff that adds a suppression or an exemption for one of those guards.
A path rule cannot see these, because the marker sits in product code or in a busy file.

`ownership` comes from the shipped default, which declares one `hogli-resolver` source at the repo root, so stamphog reads the same merged view the reviewer auto-assigner builds.

`overrides` comes from the shipped default and grants folders a ceiling of 50 files and 1000 lines.
Two folders currently take it up: [`products/desktop/`](../products/desktop/AGENT_APPROVALS.md) and [`products/visual_review/`](../products/visual_review/AGENT_APPROVALS.md).

## Proposing a change

Open a PR that edits these files.
Stamphog can never auto-approve it: the `stamphog_policy` deny category matches `.stamphog/**`, any `AGENT_APPROVALS.md`, and the engine itself, so every change routes to a human reviewer.
The loader also hard-fails if that self-governance entry is missing or loses a shipped pattern, so it cannot be dropped silently.
