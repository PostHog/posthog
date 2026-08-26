# Releasing Updates

PostHog uses semantic versioning with git tags. Patch versions are automatically computed from commit counts.

The version in `apps/code/package.json` is set to `0.0.0-dev` - this is intentional. CI injects the real version at build time from git tags.

## Version format: `major.minor.patch`

- **major.minor**: Controlled by desktop base tags (e.g., `desktop-v0.15`, `desktop-v1.0`)
- **patch**: Auto-calculated as the number of commits since the base tag that touched `products/desktop/`

**Important:** Released versions are always three-part semver (e.g., `0.22.1`). The auto-updater requires valid semver for version comparison, and CI derives the three-part version from the base tag plus the patch count.

## Auto-Update Mechanism

PostHog uses [electron-updater](https://www.electron.build/auto-update) (the npm package, not the built-in Electron autoUpdater) with the generic provider. On startup the app checks for updates against the update feed at `https://desktop-releases.posthog.com/stable`, baked into `app-update.yml` inside the app bundle at package time.

Release CI uploads the binaries and blockmaps to the feed from each platform job, then the finalize job uploads the channel files (`latest-mac.yml`, `latest.yml`) last. Updaters only see a release once the channel files change, so that upload is the publish step. The finalize job also injects the generated release notes into the channel files (the generic provider fetches nothing from GitHub, so `UpdateInfo.releaseNotes` comes from the manifest) and publishes `releases.json`, which powers the in-app release notes and What's New history. `releases.json` is built by prepending this release's generated notes to the previously published feed, so the S3 feed (not the GitHub releases API) is the source of truth for in-app notes.

GitHub Releases in `PostHog/posthog` remain the human-facing changelog and download page. Desktop releases use the existing `desktop-v*` tag namespace so they remain distinct from other monorepo products.

**macOS**: DMG + zip artifacts are uploaded; the merged `latest-mac.yml` covers both arm64 and x64 so the correct build is selected per architecture.

**Windows**: A single NSIS installer is shipped and updated through electron-updater via `latest.yml`. The legacy Squirrel.Windows installer is no longer built; anyone still on an old Squirrel install must reinstall once via the NSIS installer to keep receiving updates.

**Linux**: No auto-update. AppImage, deb and rpm packages are manual downloads from the GitHub Release, also mirrored to the S3 feed.

Remote announcements can drive this flow: a `required-update` announcement blocks apps below a version and reuses the updater; where the updater is unavailable it degrades to a manual download link. See [ANNOUNCEMENTS.md](./ANNOUNCEMENTS.md).

## How it works

1. A base tag like `desktop-v0.15` marks the start of a minor version.
2. `.github/workflows/desktop-tag.yml` (monorepo root) runs on a twice-daily schedule. It computes `desktop-vX.Y.PATCH`, where PATCH is the number of commits since the base tag that touched `products/desktop/`, waits for a quiet period, then pushes the tag.
3. The tag push triggers `desktop-release.yml`, which builds and publishes the release.
4. No manual `package.json` updates are needed.

## Releasing a patch

Merge to `master` and wait for the next scheduled `desktop-tag.yml` run. To release sooner:

- Add the `create desktop release` label to your PR before merging (the labeler must be a `team-posthog-code` member). The merge then tags immediately.
- Or trigger `desktop-tag.yml` manually with `gh workflow run desktop-tag.yml`.

## Releasing a minor or major version

Create a new base tag to bump the minor or major version:

```bash
git tag desktop-v0.16
git push origin desktop-v0.16
```

The next `desktop-tag.yml` run releases `desktop-v0.16.N`.

## Checking current version

See what version would be released:

```bash
# Find the current base tag
git tag --list 'desktop-v[0-9]*.[0-9]*' --sort=-v:refname | grep -E '^desktop-v[0-9]+\.[0-9]+(\.0)?$' | head -1

# Count desktop commits since the base tag (this is the patch number)
git rev-list desktop-v0.15..HEAD --count -- products/desktop/
```

## Tag naming convention

- **Base tags** (manual): `desktop-vX.Y` or `desktop-vX.Y.0`
- **Release tags** (auto): `desktop-vX.Y.Z`, created by CI

Only base tags are used for version calculation. Release tags are created for GitHub releases but ignored when computing the next version.
