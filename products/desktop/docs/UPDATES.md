# Releasing Updates

PostHog uses semantic versioning with git tags. Patch versions are automatically computed from commit counts.

The version in `apps/code/package.json` is set to `0.0.0-dev` - this is intentional. CI injects the real version at build time from git tags.

## Version Format: `major.minor.patch`

- **major.minor**: Controlled by git tags (e.g., `v0.15.0`, `v1.0.0`)
- **patch**: Auto-calculated as number of commits since the minor tag

**Important:** Releases must use proper three-part semver versions (e.g., `v0.22.1`, not `v0.22`). The auto-updater requires valid semver for version comparison. Two-part versions will break auto-updates.

## Auto-Update Mechanism

PostHog uses [electron-updater](https://www.electron.build/auto-update) (the npm package, not the built-in Electron autoUpdater) with the generic provider. On startup the app checks for updates against the update feed at `https://desktop-releases.posthog.com/stable`, baked into `app-update.yml` inside the app bundle at package time.

Release CI uploads the binaries and blockmaps to the feed from each platform job, then the finalize job uploads the channel files (`latest-mac.yml`, `latest.yml`) last. Updaters only see a release once the channel files change, so that upload is the publish step. The finalize job also injects the generated release notes into the channel files (the generic provider fetches nothing from GitHub, so `UpdateInfo.releaseNotes` comes from the manifest) and publishes `releases.json`, which powers the in-app release notes and What's New history. `releases.json` is built by prepending this release's generated notes to the previously published feed, so the S3 feed (not the GitHub releases API) is the source of truth for in-app notes.

GitHub Releases in `PostHog/posthog` remain the human-facing changelog and download page. Desktop releases use the existing `desktop-v*` tag namespace so they remain distinct from other monorepo products.

**macOS**: DMG + zip artifacts are uploaded; the merged `latest-mac.yml` covers both arm64 and x64 so the correct build is selected per architecture.

**Windows**: A single NSIS installer is shipped and updated through electron-updater via `latest.yml`. The legacy Squirrel.Windows installer is no longer built; anyone still on an old Squirrel install must reinstall once via the NSIS installer to keep receiving updates.

**Linux**: No auto-update. AppImage, deb and rpm packages are manual downloads from the GitHub Release, also mirrored to the S3 feed.

Remote announcements can drive this flow: a `required-update` announcement blocks apps below a version and reuses the updater; where the updater is unavailable it degrades to a manual download link. See [ANNOUNCEMENTS.md](./ANNOUNCEMENTS.md).

## How It Works

1. A base tag like `v0.15.0` marks the start of a minor version
2. Each push to `main` triggers a release with version `0.15.N` where N = commits since `v0.15.0`
3. No manual `package.json` updates needed for patch releases

## Releasing a Patch (Automatic)

Just push to `main`. The workflow computes the version automatically:

```
v0.15.0 tag exists
Push commit #1 → releases 0.15.1
Push commit #2 → releases 0.15.2
Push commit #3 → releases 0.15.3
```

## Releasing a Minor Version

Create a new base tag when you want to bump the minor version:

```bash
git tag v0.16.0
git push origin v0.16.0
```

The next push to `main` will release `0.16.1`.

## Releasing a Major Version

Same process, just increment the major:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Checking Current Version

See what version would be released:

```bash
# Find the current base tag
git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.0$' | head -1

# Count commits since base tag (this is the patch number)
git rev-list v0.15.0..HEAD --count
```

## Tag Naming Convention

- **Base tags** (manual): `vX.Y.0` - e.g., `v0.15.0`, `v1.0.0`
- **Release tags** (auto): `vX.Y.Z` - e.g., `v0.15.3`, created by CI

Only base tags (`vX.Y.0`) are used for version calculation. Release tags (`vX.Y.Z`) are created for GitHub releases but ignored when computing the next version.
