# PostHog Documentation

Developer-focused documentation alongside code. Update docs in the same PR as your code changes.

## Structure

### `published/` - Published on posthog.com

Documentation published to https://posthog.com/handbook/engineering/ when merged to master:

- Architecture guides
- Contributing guides
- Engineering practices
- Runbooks for self-hosters

**When to use**: Documentation that external users, contributors, or self-hosters need.

### `internal/` - GitHub-only

Documentation that stays in the repository:

- Development workflows
- Migration patterns
- Team processes

**When to use**: Knowledge useful for the team but not for external users. We're open source, so "internal" means GitHub-only rather than truly private.

## Publishing Flow

```
Engineer creates PR with /docs/** changes
  ↓
GitHub Action triggers posthog.com preview build
  ↓
Preview URL posted to PR
  ↓
Merge to master
  ↓
Docs go live on posthog.com
```

## Guidelines

- All published docs must have YAML frontmatter
- Use relative links between docs: `../contributing/index.md`
- Docs about PostHog internals → here
- User product docs and tutorials → posthog.com repo

## Setup

For posthog.com team setting up the integration, see the PRs in PostHog/posthog.com repo.
