# Sampo

This directory stores pending release changesets for `posthog-cli`.

Run from `cli/`:

```bash
sampo add --package cargo/posthog-cli --bump patch --message "Describe the CLI change"
```

The release workflow consumes files in `cli/.sampo/changesets/`, updates
`cli/Cargo.toml`, `cli/Cargo.lock`, and `cli/CHANGELOG.md`, then opens a
release pull request carrying that bump.
Merging that pull request runs the same approved `Release CLI` workflow
against the release commit, which creates the `posthog-cli/vX.Y.Z` GitHub
release and publishes the npm package.

Do not run `sampo publish` or push `posthog-cli/vX.Y.Z` tags manually for
`posthog-cli`; cargo-dist publishing is owned by `Release CLI`.
