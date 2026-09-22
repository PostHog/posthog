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
3. Updates to the latest `master` and stops successfully if no changesets remain
4. Runs `sampo release` from `./cli`
5. Updates `cli/Cargo.toml`, `cli/Cargo.lock`, and `cli/CHANGELOG.md`
6. Commits the release bump to `master`
7. Runs cargo-dist against the release bump commit
8. Publishes the artifacts to the release bucket, then creates the `posthog-cli/vX.Y.Z` GitHub release, refreshes `posthog-cli-latest` for stable releases, and publishes the npm package

Do not run `sampo publish`; cargo-dist owns publishing for `posthog-cli`.

### The release bucket

Artifacts are also published to `releases.posthog.com`, a shared S3 and CloudFront origin in the prod-us account, under the `posthog-cli/` prefix.
It sits alongside the other release mirrors there, `context-mill-releases` and `desktop`.
GitHub releases stay in place as a mirror.

The upload runs before the GitHub release is created, so the objects exist before anything publishes a URL that points at them.
Two key shapes, with different caching:

| Key                                                                  | Cache-Control                 | Written              |
| -------------------------------------------------------------------- | ----------------------------- | -------------------- |
| `posthog-cli/vX.Y.Z/<artifact>`                                      | `max-age=31536000, immutable` | every release        |
| `posthog-cli/install.sh`, `install.ps1`, `stable/dist-manifest.json` | `max-age=60`                  | stable releases only |

The versioned keys are immutable because the version is part of the key.
The three rolling keys are republished every release and then invalidated at the edge, so they must never carry the immutable header.
A prerelease publishes its versioned artifacts and leaves the rolling keys alone.

The step is skipped unless all three variables below are set, so a branch that predates the bucket still releases, and so a half-finished configuration cannot fail the release.
It needs three repository variables:

| Variable                         | Value                                                          |
| -------------------------------- | -------------------------------------------------------------- |
| `AWS_CLI_RELEASES_ROLE_ARN`      | the `github-posthog-cli-releases-publish-role` role in prod-us |
| `AWS_CLI_RELEASES_BUCKET`        | the shared releases bucket name                                |
| `AWS_CLI_RELEASES_CLOUDFRONT_ID` | the distribution fronting it                                   |

The role is scoped to the `posthog-cli/` prefix and to invalidations on that one distribution, so the workflow cannot touch another project's artifacts.

If you need to cut a release by hand, merge a CLI changeset to `master` and let `Release CLI` run from there.
Do not push `posthog-cli/vX.Y.Z` tags manually; cargo-dist tag-push releases are disabled.
If cargo-dist fails after `Release CLI` commits the release bump, rerun the failed jobs from the same workflow run.
Any failed job in `Release CLI` posts to the approval thread and to the [#alerts-posthog-js channel in Slack](https://posthog.slack.com/archives/C07HTMN9X47).

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
