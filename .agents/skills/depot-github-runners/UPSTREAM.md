# Upstream

Vendored from [depot/skills](https://github.com/depot/skills).

- Source: `skills/depot-github-runners/SKILL.md`
- Commit: [`7b5bc8c`](https://github.com/depot/skills/tree/7b5bc8cabd2b3b5d7dc944b622188a7a2fbec96f/skills/depot-github-runners) (2026-05-05)
- Permission: README explicitly documents `cp SKILL.md` install. No LICENSE file in upstream as of fetch date — if that changes, revisit attribution.

## Why vendored

PostHog uses `depot-ubuntu-*` runners across ~20 workflows. The upstream SKILL.md is mostly a label/size/pricing reference table that agents otherwise guess at when editing `.github/workflows/`.

## Resync

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
curl -sL "https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-github-runners/SKILL.md" \
  -o .agents/skills/depot-github-runners/SKILL.md
# then update the commit SHA above
```

Audit the diff before committing — runner sizes, pricing, and label tables drift, and we may want to trim sections we don't use (e.g. Windows/macOS).
