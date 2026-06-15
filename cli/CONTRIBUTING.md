## Releases

Releases are prepared with [Sampo](https://github.com/bruits/sampo) changesets and published by the `Release CLI`
workflow's [`cargo-dist`](https://github.com/axodotdev/cargo-dist) jobs.

When making a releasable CLI change, add a changeset from the `./cli` directory:

```bash
sampo add --package cargo/posthog-cli --bump patch --message "Describe the CLI change"
```

Use `minor` or `major` instead of `patch` when appropriate. Commit the generated file under
`cli/.sampo/changesets/` with your pull request.

After the pull request merges to `master`, the `Release CLI` workflow:

1. Checks for pending CLI changesets
2. Waits for approval in the GitHub `Release SDK` environment
3. Runs `sampo release` from `./cli`
4. Updates `cli/Cargo.toml`, `cli/Cargo.lock`, and `cli/CHANGELOG.md`
5. Commits the release bump to `master`
6. Runs cargo-dist against the release bump commit
7. Creates the `posthog-cli/vX.Y.Z` GitHub release, refreshes `posthog-cli-latest` for stable releases, and publishes the npm package

Do not run `sampo publish`; cargo-dist owns publishing for `posthog-cli`.

If you need to cut a release by hand, merge a CLI changeset to `master` and let `Release CLI` run from there.
Do not push `posthog-cli/vX.Y.Z` tags manually; cargo-dist tag-push releases are disabled.
If cargo-dist fails after `Release CLI` commits the release bump, rerun the failed jobs from the same workflow run.

The release workflow also builds `services/mcp` into `cli/lib/posthog-api-cli.mjs` before cargo-dist packages artifacts.
This keeps `posthog-cli api` aligned with the generated MCP tool catalog at release time.
To reproduce that release bundle locally, run:

```bash
pnpm --dir services/mcp run build:cli:release
```

We release semi-regularly, as new features are added. If a release breaks your CI or workflow, please open an issue on GitHub, and tag one or all of the crate authors

## Running a local build

From the `./cli` directory run `cargo install --path .` to build a new version

If you want to replace an existing installation of the CLI you will need to copy the generated target to override it:

```bash
cp ./target/release/posthog-cli "$(which posthog-cli)"
```

Tip: it can be useful to bump the version in `./cli/Cargo.toml` and run `posthog-cli --version` to ensure you're running your local version
