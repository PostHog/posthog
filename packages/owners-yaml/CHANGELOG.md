# Changelog

Notable changes to the `owners-yaml` package. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

`publish-owners-yaml.yml` reads the section matching the tagged version and uses it as
the GitHub Release body, so add the entry here before you cut the tag.

## Unreleased

### Added

- An optional `additions` field, at file level and in rules, names the owners of additions below a directory, separate from the owners of the files in it. The format only names them; a consumer decides what counts as an addition and what to do with the list. Unlike `owners`, the owners of additions from every file on the walk and every matching rule add up, and `inherit: false` still cuts them. `SPEC.md` section 3.6 defines it.
- The resolver response carries an `additions` member, and `Resolution` an `additions` field. Consumers that ignore unknown members, as SPEC section 7.4 requires, are unaffected. SPEC section 7.4 requires a consumer to treat a missing member as an empty array.
- `lint` fails on a rule that names a tracked directory without the trailing `/`, such as `docs` for `docs/`. A literal last segment also matches a file of that name, so the slash says which one is meant.
- Conformance cases may state `additions`. A case that leaves it out expects an empty list, so existing cases need no edit.

### Changed

- Path normalization removes a trailing `/`. `products/new/` and `products/new` now resolve alike; before, the slash put the directory's own ownership file on the walk.
- Every matching rule in a file now applies, and each replaces only the fields it sets. Before, the last matching rule replaced the earlier ones entirely, so a rule that set only `status` dropped the `owners` an earlier rule had set. `SPEC.md` section 3.4 records the amendment.

## 0.2.1

### Added

- `--producer NAME` on `owners resolve` and on `python -m owners_yaml`, and a `producer` argument on `OwnersResolver`. Without it, a team that maps `notifications` per producer was never matched, so every bot fell back to the team's `slack` channel. A name the root file's `producers` list does not declare is an error, because it would silently route to the people channel. SPEC section 7.1 now defines the producer as part of a resolver request.

### Docs

- The `notifications` example in the README and the command next to it now agree: a per-producer mapping needs `--purpose notifications --producer review-bot`. A plain channel string covers all automation.
- The install section warns that the PyPI project named `owners` is a different package. Always write `owners-yaml`.
- "Lint in CI" says what plain `lint` does not check: it does not know which teams exist, `lint --live` asks GitHub through the `gh` CLI, and `who` and `resolve` answer from the parent directory when a file does not parse.
- SPEC section 10 and the README record a non-goal: CODEOWNERS is an export target and a one-time migration source, never a second input format.

## 0.2.0

First release on PyPI, as `owners-yaml`. The package was developed in the monorepo as `posthog-owners` and never published under that name.

### Added

- `SPEC.md` defines the `owners.yaml` format, version 1, with the resolution steps, a field merge table, a flow diagram, and a worked example. `owners.schema.json` describes the file for editors.
- `SPEC.md` section 7 defines the resolver interface, and `resolution.schema.json` describes its JSON response.
- `conformance/` holds language-neutral test cases for the resolution rules, which any implementation can run.
- `publish-owners-yaml.yml` publishes the package to PyPI when an `owners-yaml-v*` tag is pushed.
- Root-only repo settings in `owners.yaml`: `github_org`, `producers`, `reserved_dirs`, `alias_files`, and `codeowners`.
- `alias_files` declares the file names, besides `owners.yaml`, that count as ownership files. It defaults to `[product.yaml]`, so a root file that predates the setting keeps resolving as before; a declared list replaces the default, and `alias_files: []` turns alias files off.
- `--repo-root` on every CLI command, and `--org` on `lint` and `codeowners`.
- A tree that is not a git worktree is read from disk, so the CLI works on an export or a scratch copy.
- `owners_yaml.github.GitHubOrg` validates team slugs and handles without any host tooling.
- An `owners-yaml` console script, so `uvx owners-yaml` works without `--from`.
- `BatchOwnershipSource`, a source that fetches a batch's ownership files together. `OwnersResolver.map()` calls its `read_all` before it reads any file: first for the root `owners.yaml`, then for the batch.
- The top-level `owners_yaml` package exports the full public API, so consumers do not import submodules.
- `py.typed`, so type checkers read the package's annotations.

### Fixed

- Rule patterns support `[abc]`, `[a-z]` and `[!abc]` character classes, as SPEC section 3.5 now states. `match_is_glob` already counted `[` as a wildcard, so such a pattern passed lint, counted as a crosscutting glob, then matched nothing and let its paths fall through to an ancestor's owner.

### Changed

- The GitHub organization is no longer hardcoded. `codeowners` and `lint --live` read it from `github_org` or `--org`, and fail with a clear message when neither is set.
- Producer names are no longer hardcoded. A repo that declares `producers` gets typo checks; a repo that does not accepts any name.
- The reserved `products/**/mcp/**` location moved from the code into PostHog's own `reserved_dirs`. `.github/workflows/**` stays built in.
- The CODEOWNERS projection reads its Jest spelling rules from the `codeowners` settings instead of PostHog's layout.
- Outside a git worktree and without `--repo-root`, the CLI prints an error instead of a traceback.
- `version: true` and `version: 1.0` no longer count as `version: 1`, so such a file counts as absent.
- `product.yaml` is no longer a PostHog convention baked into the code. It is the default value of `alias_files`, which a root file can replace or empty.

## 0.1.0

First version, used inside the PostHog monorepo only.
