---
name: getting-prs-approved
description: >
  Gets a PostHog/posthog PR approved and merged with minimal waiting. Checks stamphog
  auto-approval eligibility with the local gates dry-run, fixes what blocks it (size
  ceiling, deny-list categories, title words, unresolved bot findings), manages the
  stamphog label lifecycle, and routes gated PRs to the fastest human approval path
  (priority-review label, owner-targeted asks). Use when a PR needs a stamp, review,
  or approval, when stamphog refused or removed its label, when deciding whether a PR
  can be auto-approved, or before opening a PR to make it stampable.
---

# Getting PRs approved

PostHog/posthog has two review tracks: **stamphog** (the auto-approval agent, triggered by the `stamphog` label) typically approves eligible PRs within the hour, while human review commonly takes half a day to several days depending on reviewer availability. Aim every PR at the stamphog track when eligible; when gated, escalate deliberately instead of waiting.

## Step 1 — check the gates locally (no LLM call, seconds)

```bash
uv run tools/pr-approval-agent/review_pr.py <PR_NUMBER> --dry-run
```

Runs stamphog's deterministic gates only (prerequisites, deny-list, size, tier). Requires `gh` auth. Do this **before** applying the label — it reports exactly why a PR would be refused.

## Stamphog policy summary

Source of truth is `tools/pr-approval-agent/gates.py` and its README — re-check there if behavior surprises you.

**Hard prerequisites:** not a draft, no merge conflicts, no outstanding changes-requested review, human author (bot-authored PRs are always refused).

**Size ceiling:** ≤500 changed lines (additions + deletions) and ≤20 files. Generated files count.

**Deny categories** — any match forces human review. Matching runs on **file paths and the PR title**, so a title word alone can trip a category:

| Category       | Trips on                                                                                                                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| auth           | auth/login/signup/oauth/saml/sso/oidc/credential/password/2fa/mfa (title or path); `permission` paths                                       |
| crypto_secrets | crypto/encrypt/decrypt/vault; paths containing secret, api_key, private_key, `.env`, `.pem`                                                 |
| migrations     | any `migrations/` path — see the analyzer bypass below                                                                                      |
| infra_cicd     | `.github/workflows`, dockerfile, docker-compose, deploy, k8s paths; terraform/kubernetes/helm in the title                                  |
| billing        | billing/payment/stripe/invoice/subscription/pricing — title counts                                                                          |
| public_api     | openapi, api_schema, swagger, public_api — a title like "regenerate openapi types" trips it                                                 |
| deps_toolchain | package.json, lockfiles (pnpm-lock, Cargo.lock, uv.lock…), pyproject.toml, requirements.txt, go.mod, Makefile, Dockerfile, tsconfig, .nvmrc |

**Bot findings:** stamphog independently verifies confirmed reviewer-bot findings (e.g. greptile P1s) in source and escalates instead of approving. Resolve or explicitly rebut them before labeling.

**Migrations bypass:** the Backend CI migration analyzer marks safe migrations (the `stamphog:v1` marker), which stamphog then ignores for deny purposes. If the PR's only deny hit is safe migrations, **wait for the Backend CI migration check to finish before labeling** — labeling early returns "Migration risk check pending; re-label after it completes."

## Step 2 — make it stampable (often a 5-minute restructure)

1. **Quarantine deny files.** A lockfile bump, workflow edit, or migration inside a feature PR drags the whole PR onto the human track. Move them to their own minimal PR.
2. **Fix the title.** Strip deny words (billing, openapi, auth, deploy…) from titles when the change isn't actually in that domain.
3. **Trim below 500 lines / 20 files** — but don't over-split; see `slicing-prs`.
4. **Resolve confirmed bot findings** with a fix or a rebuttal comment.

## Step 3 — apply the label and understand its lifecycle

```bash
gh pr edit <PR> --add-label stamphog
```

- **APPROVED** → the label stays on (marks the PR as stamphog'd). The approval comes from github-actions[bot] and counts for branch protection.
- **REFUSE / ESCALATE** → the label is stripped. Address the feedback, then **re-apply the label** — it does not retry on its own.
- **ERROR** (LLM backend outage) → the label stays and the review retries on the next push.
- **New pushes:** trivial deltas (tests/docs/lockfile/generated paths, clean merges from the base branch) retain the approval; anything else dismisses it and auto re-reviews. Avoid pushing cosmetic changes onto an already-approved PR.

## Step 4 — human track (when genuinely gated)

Most stamphog denials still end in a human approval — a denial mostly means added latency, so escalate immediately rather than waiting passively:

1. **Apply the `priority-review` label** — it auto-posts the PR to #dev-stamp-exchange (`gh pr edit <PR> --add-label priority-review`). Costs nothing, do it first.
2. **Ask a specific likely approver.** Find the owning team with the `establishing-code-ownership` skill, then check who recently approved merged PRs touching the same paths (`gh pr view <n> --json reviews` on a few of them). A targeted ask to someone currently online resolves in minutes; untargeted channel posts often need a follow-up ping. Offering a reciprocal review speeds things up.
3. **Team-channel group ping** for team-owned code (migrations, ClickHouse, cross-team files) with a one-line risk summary — these never pass stamphog, and generic stamp-exchange posts for them tend to go unanswered.

**Timing:** review capacity clusters in reviewer timezones. Post asks early in your overlap window, and pre-announce PRs that will be ready late in your day so a reviewer expects them.

**Other repos:** stamphog only runs in PostHog/posthog. PRs in sibling repos (charts, cloud infra) are always human-track — batch them, post early, and name a reviewer.
