# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by PostHog's container-image CI/CD (`depot/build-push-action`, `depot/setup-action`).

- Source: `skills/depot-container-builds/SKILL.md`
- Commit: [`81795ab`](https://github.com/depot/skills/tree/81795abf98f81fb112cda35720e19b2aa3efa640/skills/depot-container-builds) (2026-09-01)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

## Resync

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
curl -sL "https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-container-builds/SKILL.md" \
  -o .agents/skills/depot-container-builds/SKILL.md
# Update the `Commit:` link above with the new SHA and date.
```
