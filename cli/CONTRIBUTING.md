## Releases

Releases are cut by pushing a release tag to the repository, for the `posthog-cli` app. Generally we want to do this on a branch,
and bump the package version number at the same time.

```bash
git checkout -b "cli/release-v0.1.0-pre1"
# Bump version number in Cargo.toml and build to update Cargo.lock
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

## Running a local build

From the `./cli` directory run `cargo install --path .` to build a new version

If you want to replace an existing installation of the CLI you will need to copy the generated target to override it:

```bash
cp ./target/release/posthog-cli "$(which posthog-cli)"
```

Tip: it can be useful to bump the version in `./cli/Cargo.toml` and run `posthog-cli --version` to ensure you're running your local version
