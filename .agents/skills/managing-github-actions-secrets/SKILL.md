---
name: managing-github-actions-secrets
description: >
  Creates and updates GitHub Actions secrets for PostHog workflows. Use when
  adding a new CI secret, rotating an existing secret, wiring a workflow to an
  API token, package registry credential, deploy key, or any value referenced
  via `${{ secrets.* }}` in `.github/workflows/`.
---

# Managing GitHub Actions secrets for PostHog

PostHog centralizes all GitHub Actions secrets at the **organization** level
and grants individual repositories access to them. Do not add secrets to a
single repo, even if the secret is only consumed by one workflow today.

## The rule

- **Always** create secrets on the `posthog` org, not on a repo.
- Grant the secret to specific repos via the org-level access control
  (selected repositories). Do not make it available to all repos by default
  unless the secret is genuinely meant to be shared org-wide.
- Never paste secret values into chat, PR descriptions, commit messages, or
  files. Pipe them in, or paste them only into the GitHub UI's secret field.

## Creating or updating a secret via `gh` CLI

Pipe the secret value into `gh secret set` with `--org posthog`. The example
below reads the value from stdin so it never appears in shell history:

```sh
# Read from clipboard / a pipe / a file — never inline as an argument
pbpaste | gh secret set POSTHOGOS_PACKAGER_KEY --org posthog
```

Common variants:

```sh
# From a file
gh secret set POSTHOGOS_PACKAGER_KEY --org posthog < secret.txt

# Restrict to selected repositories at creation time
gh secret set POSTHOGOS_PACKAGER_KEY --org posthog \
  --visibility selected --repos PostHog/posthog,PostHog/posthog-foss

# Update which repos can access an existing org secret
gh secret set POSTHOGOS_PACKAGER_KEY --org posthog \
  --visibility selected --repos PostHog/posthog
```

Verify:

```sh
gh secret list --org posthog | grep POSTHOGOS_PACKAGER_KEY
```

## Creating or updating a secret via the GitHub UI

1. Open <https://github.com/organizations/PostHog/settings/secrets/actions>.
2. Click **New organization secret** (or the existing secret to update it).
3. Set the **Name** (SCREAMING_SNAKE_CASE, descriptive, like `POSTHOGOS_PACKAGER_KEY`).
4. Paste the **Value**.
5. Under **Repository access**, choose **Selected repositories** and pick the
   exact repos that need it. Avoid **All repositories** unless the secret is
   safe to expose to every repo in the org.
6. Click **Add secret** / **Update secret**.

## What not to do

- Do not run `gh secret set NAME` without `--org posthog` — that creates a
  repo-level secret on whatever repo `gh` is currently pointed at.
- Do not navigate to `Settings → Secrets and variables → Actions` on an
  individual repo to add a secret. If a repo-level secret already exists for
  something that should be org-level, migrate it (create at org, grant to the
  repo, then delete the repo-level copy).
- Do not echo secret values in commands, logs, or files. If a value was
  accidentally exposed, rotate it immediately.

## When the user asks "where do I add this secret?"

Default answer: at the org level via `gh secret set --org posthog`, granted
to the specific repos that need it. Only deviate if the user explicitly
overrides this (e.g. for an environment-scoped secret on a deployment
environment, which is a different mechanism).
