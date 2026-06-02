# Sampo

This directory stores pending release changesets for `posthog-cli`.

Run from `cli/`:

```bash
sampo add --package cargo/posthog-cli --bump patch --message "Describe the CLI change"
```

The release workflow consumes files in `cli/.sampo/changesets/`, updates
`cli/Cargo.toml`, `cli/Cargo.lock`, and `cli/CHANGELOG.md`, then pushes the
`posthog-cli/vX.Y.Z` tag used by the cargo-dist workflow.

Do not run `sampo publish` for `posthog-cli`; cargo-dist owns publishing.
