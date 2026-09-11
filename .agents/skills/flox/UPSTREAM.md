# Upstream

Vendored from [flox/flox-skills](https://github.com/flox/flox-skills) for work on PostHog's established Flox environment.

- Source: `flox-plugin/skills/flox/`
- Commit: [`a96f609e609b913f1ef748da4adbbdf29a72fb83`](https://github.com/flox/flox-skills/tree/a96f609e609b913f1ef748da4adbbdf29a72fb83/flox-plugin/skills/flox) (2026-09-10T09:13:18-05:00)
- License: Apache License, Version 2.0. `LICENSE` is copied from the upstream repository root at this commit.
- NOTICE: upstream has no `NOTICE` file at this commit.

No files are omitted from `flox-plugin/skills/flox/`. This repository does not vendor the upstream `floxify` skill, plugin or marketplace manifests, evals, fixtures, reports, CI, repository-level `.flox` environment, or synchronization workflows.

`floxify` is excluded because PostHog already has an established Flox environment. Its repository-conversion workflow, bundled scripts, and discovery slot do not support routine maintenance of that environment.

## Local modifications

`SKILL.md` differs from upstream only in these marked changes:

- The frontmatter description triggers only for explicit Flox work and excludes ordinary language or package-manager dependency work.
- The upstream instruction to use the skill first for every new project, application, demo, server, or codebase is removed with that description.
- The marked "PostHog repository safeguards" section requires agents to inspect and preserve the existing Flox configuration and activation files.
- The local section prohibits `flox init`, replacing `.flox`, or redesigning the setup unless the user explicitly requests that work.

`UPSTREAM.md` and `LICENSE` are local additions outside the upstream skill directory. The repository Markdown formatter, Markdown lint config, and Git whitespace attributes exclude this vendored directory so upstream Markdown remains byte-for-byte unchanged.

## Manual resync

The resync overwrites `SKILL.md`, so reapply every local modification above afterward.

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
UPSTREAM_REPO=https://github.com/flox/flox-skills.git
UPSTREAM_COMMIT=$(git ls-remote "$UPSTREAM_REPO" refs/heads/main | awk '{print $1}')
TMP_DIR=$(mktemp -d)

git clone --filter=blob:none --no-checkout "$UPSTREAM_REPO" "$TMP_DIR/flox-skills"
git -C "$TMP_DIR/flox-skills" checkout --detach "$UPSTREAM_COMMIT"
rsync -a --delete \
  --exclude LICENSE \
  --exclude UPSTREAM.md \
  "$TMP_DIR/flox-skills/flox-plugin/skills/flox/" \
  "$REPO_ROOT/.agents/skills/flox/"
cp "$TMP_DIR/flox-skills/LICENSE" "$REPO_ROOT/.agents/skills/flox/LICENSE"
git -C "$TMP_DIR/flox-skills" show -s --format='Commit: %H%nDate: %cs' HEAD
rm -rf "$TMP_DIR"

# Reapply the marked frontmatter and repository-safeguard changes in SKILL.md.
# Update the commit, date, license, NOTICE status, omissions, and local modifications above.
git diff -- .agents/skills/flox
```

After resyncing, verify relative references, compare the vendored tree with the new commit, run `hogli lint:skills`, and run the repository Markdown checks.
