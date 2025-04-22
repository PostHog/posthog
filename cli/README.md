# The Posthog CLI

```bash
> posthog-cli --help
The command line interface for PostHog 🦔

Usage: posthog-cli [OPTIONS] <COMMAND>

Commands:
  login      Interactively authenticate with PostHog, storing a personal API token locally. You can also use the environment variables `POSTHOG_CLI_TOKEN` and `POSTHOG_CLI_ENV_ID`
  query      Run a SQL query against any data you have in posthog. This is mostly for fun, and subject to change
  sourcemap  Upload a directory of bundled chunks to PostHog
  help       Print this message or the help of the given subcommand(s)

Options:
      --host <HOST>  The PostHog host to connect to [default: https://us.posthog.com]
  -h, --help         Print help
  -V, --version      Print version
```

## Env-based Authentication

You can authenticate with PostHog interactively for using the CLI locally, but if you'd like to use it in a CI/CD pipeline, we recommend using these environment variables:
- `POSTHOG_CLI_TOKEN`: [A posthog person API key.](https://posthog.com/docs/api#private-endpoint-authentication)
- `POSTHOG_CLI_ENV_ID`: The ID number of the project/environment to connect to. E.g. the "2" in `https://us.posthog.com/project/2`

## Releases

Releases are cut by pushing a release tag to the repository, for the `posthog-cli` app. Generally we want to do this on a branch,
and bump the package version number at the same time.
```bash
git checkout -b "cli/release-v0.1.0-pre1"
# Bump version number in Cargo.toml
git add .
git commit -m "Bump version number"
git tag "posthog-cli-v0.1.0-prerelease.1"
git push
git push --tags
# Optional - also publish to crates.io
cd cli && cargo publish
```

We manage publishing releases through [`cargo-dist`](https://github.com/axodotdev/cargo-dist)

We release semi-regularly, as new features are added. If a release breaks your CI or workflow, please open an issue on GitHub, and tag one or all of the crate authors
