# .stamphog

The PostHog monorepo's own stamphog configuration.

How the hosted product reads this directory: [`products/stamphog/README.md`](../products/stamphog/README.md#customize-the-review-for-your-repository).
What each file contains and how per-folder overrides resolve: [the engine's "Policy files" section](../products/stamphog/packages/pr-approval-agent/README.md#policy-files).

## What this repository configures

`policy.yml` keeps the shipped defaults for `size_gate`, `tiers`, `overrides`, `familiarity` and `ownership`.
It overrides `deny` and `allow`, and the differences are:

- `auth` and `billing` exempt `products/warehouse_sources/backend/temporal/data_imports/sources/`, because connector code does OAuth and talks to the Stripe API without touching PostHog's auth system or its billing.
- `infra_cicd` also matches `.github/pr-deploy`.
- `stamphog_policy` also matches `products/stamphog/backend/logic/policy_defaults/`, `tools/owners/`, `owners.yaml` and `product.yaml`, because those are gate inputs here.
- `allow` also lists `.github/CODEOWNERS`.
- Every `rationale` records the false positives that shaped the rule in this repository.

`review-guidance.md` replaces the default norms.
It differs from the default in six lines:

- Ownership is read from `owners.yaml` and `product.yaml` rather than CODEOWNERS, in two places.
- Risky territory names event ingestion paths, where the default names data ingestion or write paths.
- The opt-in signal is described as the stamphog label, where the default describes the repository's review settings and the label in label mode.
- The incidental-keyword example is a warehouse connector fix.
- The philosophy line says "We move fast" rather than "Move fast".

There is no `steering.md`.

`ownership` declares one `hogli-resolver` source at the repo root, so stamphog reads the same merged view the reviewer auto-assigner builds.

`overrides` grants folders a ceiling of 50 files and 1000 lines.
Two folders currently take it up: [`products/desktop/`](../products/desktop/AGENT_APPROVALS.md) and [`products/visual_review/`](../products/visual_review/AGENT_APPROVALS.md).

## Proposing a change

Open a PR that edits these files.
Stamphog can never auto-approve it: the `stamphog_policy` deny category matches `.stamphog/**`, any `AGENT_APPROVALS.md`, and the engine itself, so every change routes to a human reviewer.
The loader also hard-fails if that self-governance entry is ever missing, so it cannot be dropped silently.
