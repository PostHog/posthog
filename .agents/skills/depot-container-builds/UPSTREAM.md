# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by PostHog's container-image CI/CD (`depot/build-push-action`, `depot/setup-action`).

- Source: `skills/depot-container-builds/SKILL.md`
- Commit: [`71f008d`](https://github.com/depot/skills/tree/71f008de4dbfa8625ece3df85019bc914b9399a0/skills/depot-container-builds) (2026-10-15)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

## Local additions

In `SKILL.md`: the "things already tried" paragraph between the PostHog-local comment markers, which points at `docs/internal/ci-things-already-tried.md`.

## Resync

The resync overwrites `SKILL.md`, so re-apply the local addition afterwards.

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
cp .agents/skills/depot-container-builds/SKILL.md /tmp/depot-container-builds-local.md
curl -sL "https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-container-builds/SKILL.md" \
  -o .agents/skills/depot-container-builds/SKILL.md
diff /tmp/depot-container-builds-local.md .agents/skills/depot-container-builds/SKILL.md
# Re-add the local paragraph, then update the `Commit:` link above with the new SHA and date.
```
