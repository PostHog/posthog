# Upstream

Vendored from [depot/skills](https://github.com/depot/skills).

- Source: `skills/depot-container-builds/SKILL.md`
- Commit: [`7b5bc8c`](https://github.com/depot/skills/tree/7b5bc8cabd2b3b5d7dc944b622188a7a2fbec96f/skills/depot-container-builds) (2026-05-05)
- Permission: README explicitly documents `cp SKILL.md` install. No LICENSE file in upstream as of fetch date — if that changes, revisit attribution.

## Why vendored

PostHog uses `depot/build-push-action` and `depot/setup-action` across the container-image CI/CD workflows. The upstream SKILL.md documents `depot build`, `depot bake`, multi-platform builds, and cache flags that agents otherwise have to infer.

## Resync

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
curl -sL "https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-container-builds/SKILL.md" \
  -o .agents/skills/depot-container-builds/SKILL.md
# Then update the `Commit:` line above (both the short SHA in the link text
# and the full SHA in the URL) and bump the date.
```

Audit the diff before committing — CLI flags and registry syntax drift; trim sections we don't use.
