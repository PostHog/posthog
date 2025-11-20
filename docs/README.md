# PostHog Documentation

Developer-focused documentation alongside code. Update docs in the same PR as your code changes.

## Structure

### `published/` - Published on posthog.com

Documentation published to https://posthog.com/handbook/engineering/ when merged to master:

- Architecture guides
- Contributing guides
- Engineering practices

**When to use**: Documentation that external users or contributors need.

### `internal/` - GitHub-only

Documentation that stays in the repository:

- Development workflows
- Migration patterns
- Team processes

**When to use**: Knowledge useful for the team but not for external users. We're open source, so "internal" means GitHub-only rather than truly private.

## Publishing Flow

```text
Engineer creates PR with /docs/published/** changes
  ↓
GitHub Action triggers posthog.com preview build
  ↓
Preview URL posted to PR
  ↓
Merge to master
  ↓
Docs go live on posthog.com
```

The posthog.com Gatsby build uses gatsby-source-git to clone this monorepo and pull files from `/docs/published/` during the build process.

## Guidelines

- All published docs must have YAML frontmatter
- Use relative links between docs: `../contributing/index.md`
- Docs about PostHog internals → here
- User product docs and tutorials → posthog.com repo

## Setup

For posthog.com team setting up the integration, see the PRs in PostHog/posthog.com repo.
