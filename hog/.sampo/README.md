# Sampo

This directory stores pending release changesets for `hog`.

Run from `hog/`:

```bash
sampo add --package npm/@posthog/hog --bump patch --message "Describe the change"
```

The `Release hog` workflow consumes the files in `hog/.sampo/changesets/`, bumps `hog/package.json` and updates `hog/CHANGELOG.md`, then opens a release pull request with that bump.
Merging it runs the workflow again, which builds and publishes the version.
While hog's version is a prerelease, such as `0.1.0-alpha.0`, every changeset bumps the prerelease number, and sampo keeps the consumed changesets in `hog/.sampo/prerelease/` until the version drops its suffix.

Do not run `sampo publish` or push `hog/v*` tags by hand.
