# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by PostHog workflows pinning `depot-ubuntu-*` runners.

- Source: `skills/depot-github-runners/SKILL.md`
- Commit: [`71f008d`](https://github.com/depot/skills/tree/71f008de4dbfa8625ece3df85019bc914b9399a0/skills/depot-github-runners) (2026-10-15)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

## Local additions

In `SKILL.md`: the "Depot runners are not Depot CI" section between the PostHog-local comment markers, and the sentence appended to the frontmatter `description` that sends Depot CI questions to the `depot-ci` skill.

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
