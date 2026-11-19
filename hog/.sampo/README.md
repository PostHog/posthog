# Sampo

This directory stores pending release changesets for `hog`.

Run from `hog/`:

```bash
sampo add --package npm/hog --bump patch --message "Describe the change"
```

The `Release hog` workflow consumes the files in `hog/.sampo/changesets/`, bumps `hog/package.json` and updates `hog/CHANGELOG.md`, then opens a release pull request with that bump.
Merging it runs the workflow again, which builds and publishes the version.
The file name says when a changeset releases. `weekly-<name>.md`, and the `pr-<number>.md` changesets CI adds, wait for the weekly release on Tuesdays. Any other name starts a release when it merges. Rename the file `sampo add` writes after the change, with the `weekly-` prefix when it can wait.
hog starts at `0.0.0`, so the first release, made of `minor` changesets, is `0.1.0`.

Do not run `sampo publish` or push `hog/v*` tags by hand.
