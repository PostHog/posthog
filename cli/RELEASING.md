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

To smoke-test the packaged CLI before cutting a release, build the same cargo-dist archive and installer locally,
then run both the unpacked archive and the generated shell installer from a temporary home directory:

```bash
flox activate -- bash -c 'cargo install cargo-dist --version 0.32.0 --locked'
DIST_BIN="$HOME/.cargo/bin/dist" flox activate -- bash -c './cli/scripts/smoke-release-artifact.sh'
```

If you are testing uncommitted local changes, set `CLI_RELEASE_SMOKE_ALLOW_DIRTY=1` for the second command.
The smoke test verifies that the archive includes `lib/posthog-api-cli.mjs`, that `posthog-cli api --agent-help` works from the unpacked artifact, and that the generated shell installer produces a working `posthog-cli api` install without relying on a PostHog repo checkout.
It serves `target/distrib` on `127.0.0.1:8765` while testing the installer; set `CLI_RELEASE_SMOKE_PORT` if that port is already in use.
It does not replace any `posthog-cli` already on your `PATH`; to manually test the built artifact, run `target/distrib/posthog-cli-$(rustc -vV | sed -n 's/^host: //p')/posthog-cli api --agent-help`.

We release semi-regularly, as new features are added. If a release breaks your CI or workflow, please open an issue on GitHub, and tag one or all of the crate authors
