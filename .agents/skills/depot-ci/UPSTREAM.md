# Upstream

Vendored from [depot/skills](https://github.com/depot/skills) — used by the Depot CI workflows this repo keeps under `.depot/workflows/`.

- Source: `skills/depot-ci/SKILL.md` and `skills/depot-ci/references/`
- Commit: [`71f008d`](https://github.com/depot/skills/tree/71f008de4dbfa8625ece3df85019bc914b9399a0/skills/depot-ci) (2026-10-15)
- License: none in upstream at this commit; README documents `cp SKILL.md` install.

Upstream also ships `agents/openai.yaml`, `assets/` icons and `references/test-splitting.md` in this directory. None is vendored: we do not run the OpenAI agent definition, the icons are branding for Depot's own docs, and PostHog does not use Depot test splitting.

## Local additions

- `references/posthog-check-run-semantics.md`, which upstream has no equivalent of.
- In `SKILL.md`, the three sections between PostHog-local comment markers (one under the intro, one under "Parallel Steps" recording that GitHub Actions now has its own `parallel:` keyword, and one under "Test Results and Timing-Based Splitting" that replaces upstream's splitting sentences and its link to `references/test-splitting.md`), and the two sentences appended to the frontmatter `description`.
- In `references/oidc.md`, the trust policy JSON as reflowed by the repo formatter.
- Three code fences tagged `text` to satisfy markdownlint MD040, which the pre-commit hook enforces: the directory tree in `SKILL.md` and `references/migration.md`, and the SPIFFE id in `references/oidc.md`. Upstream leaves them untagged, so a resync reintroduces the error.
- One of two consecutive blank lines after the runner label table in `references/github-actions-compatibility.md`, which markdownlint MD012 rejects.

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
