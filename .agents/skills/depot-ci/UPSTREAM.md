# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by the Depot CI workflows this repo keeps under `.depot/workflows/`.

- Source: `skills/depot-ci/SKILL.md` and `skills/depot-ci/references/`
- Commit: [`81795ab`](https://github.com/depot/skills/tree/81795abf98f81fb112cda35720e19b2aa3efa640/skills/depot-ci) (2026-09-01)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

Upstream also ships `agents/openai.yaml` and `assets/` icons in this directory. Neither is vendored: we do not run the OpenAI agent definition, and the icons are branding for Depot's own docs.

## Local additions

- `references/posthog-check-run-semantics.md`, which upstream has no equivalent of.
- In `SKILL.md`, the paragraph between the PostHog-local comment markers, and the two sentences appended to the frontmatter `description`.
- Three code fences tagged `text` to satisfy markdownlint MD040, which the pre-commit hook enforces: the directory tree in `SKILL.md` and `references/migration.md`, and the SPIFFE id in `references/oidc.md`. Upstream leaves them untagged, so a resync reintroduces the error.

## Resync

The resync overwrites `SKILL.md`, so re-apply the local additions afterwards.

```bash
SHA=$(curl -s https://api.github.com/repos/depot/skills/commits/main | jq -r .sha)
BASE=https://raw.githubusercontent.com/depot/skills/$SHA/skills/depot-ci
cp .agents/skills/depot-ci/SKILL.md /tmp/depot-ci-local.md
curl -sfL "$BASE/SKILL.md" -o .agents/skills/depot-ci/SKILL.md
for r in github-actions-compatibility migration oidc runs-and-debugging secrets-and-variables; do
  curl -sfL "$BASE/references/$r.md" -o ".agents/skills/depot-ci/references/$r.md"
done
diff /tmp/depot-ci-local.md .agents/skills/depot-ci/SKILL.md
# Re-add the local paragraph and the description sentences, then update `Commit:` above.
# Check whether upstream added or renamed reference files; the loop above is a fixed list.
```
