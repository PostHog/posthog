# Sampo

This directory stores pending release changesets for `hog`.

Run from `hog/`:

```bash
sampo add --package npm/hog --bump patch --message "Describe the change"
```

The `Release hog` workflow consumes the files in `hog/.sampo/changesets/`, bumps `hog/package.json` and updates `hog/CHANGELOG.md`, then opens a release pull request with that bump.
Merging it runs the workflow again, which builds and publishes the version.
The file name says when a changeset releases. `weekly-<name>.md` waits for the weekly release on Tuesdays, and so do the `weekly-pr-<number>.md` changesets CI once added. Any other name starts a release when it merges. Rename the file `sampo add` writes after the change, with the `weekly-` prefix when it can wait.
A change that reaches hog only through code compiled into it, like the MCP code in `services/mcp/`, needs no changeset: each release adds one for the pull requests that changed compiled files without one, and the weekly run releases for it alone. The Releases section of `hog/README.md` says when to add one anyway, and whether to bump `patch` or `minor`.
hog starts at `0.0.0`, so the first release, made of `minor` changesets, is `0.1.0`.

Do not run `sampo publish` or push `hog/v*` tags by hand.
