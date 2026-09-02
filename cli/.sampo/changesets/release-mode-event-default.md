---
cargo/posthog-cli: minor
---

Default `--release-mode` to `event` for `sourcemap inject`, `sourcemap process`, `sourcemap upload`, `hermes inject`, `hermes clone` and `hermes upload`. Uploaded symbol sets and source maps are now release-independent, and each exception resolves its own release: a web build reads the `_posthogReleaseId` injected into the chunk, and a Hermes build resolves it from the `$app_namespace` / `$app_version` / `$app_build` the SDK already sends. Two releases that ship the same code keep one symbol set instead of colliding on the release that uploaded it first. Pass `--release-mode symbol-set` to keep binding the release to what you upload. Before upgrading, check that the release coordinates you pass match the app's bundle identifier or applicationId, version and build number, because a mismatch leaves exceptions with no release.

`hermes upload` now resolves `--info-plist` before it checks the release coordinates. An iOS build that supplies them that way no longer gets a warning about a release the run creates correctly.
