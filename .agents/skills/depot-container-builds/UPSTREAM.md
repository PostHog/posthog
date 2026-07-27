# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by PostHog's container-image CI/CD (`depot/build-push-action`, `depot/setup-action`).

- Source: `skills/depot-container-builds/SKILL.md`
- Commit: [`7b5bc8c`](https://github.com/depot/skills/tree/7b5bc8cabd2b3b5d7dc944b622188a7a2fbec96f/skills/depot-container-builds) (2026-05-05)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

## Resync

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
curl -sL "https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-container-builds/SKILL.md" \
  -o .agents/skills/depot-container-builds/SKILL.md
# Update the `Commit:` link above with the new SHA and date.
```
