# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by PostHog workflows pinning `depot-ubuntu-*` runners.

- Source: `skills/depot-github-runners/SKILL.md`
- Commit: [`7b5bc8c`](https://github.com/depot/skills/tree/7b5bc8cabd2b3b5d7dc944b622188a7a2fbec96f/skills/depot-github-runners) (2026-05-05)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

## Local additions

Two things in this directory are ours, not upstream's:

- `references/depot-ci-check-runs.md`, which upstream has no equivalent of.
- In `SKILL.md`, the "Depot runners are not Depot CI" section between the PostHog-local comment markers, and the Depot CI sentences appended to the frontmatter `description`.

## Resync

The resync overwrites `SKILL.md`, so re-apply the local additions afterwards.

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
cp .agents/skills/depot-github-runners/SKILL.md /tmp/depot-skill-local.md
curl -sL "https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-github-runners/SKILL.md" \
  -o .agents/skills/depot-github-runners/SKILL.md
diff /tmp/depot-skill-local.md .agents/skills/depot-github-runners/SKILL.md
# Re-add the local section and the description sentences, then update `Commit:` above.
```
