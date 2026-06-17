## Releasing

See [RELEASING.md](./RELEASING.md) for the full release process.

## Running a local build

From the `./cli` directory run `cargo install --path .` to build a new version

If you want to replace an existing installation of the CLI you will need to copy the generated target to override it:

```bash
cp ./target/release/posthog-cli "$(which posthog-cli)"
```

Tip: it can be useful to bump the version in `./cli/Cargo.toml` and run `posthog-cli --version` to ensure you're running your local version
