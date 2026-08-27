---
cargo/posthog-cli: minor
---

Add `--release-mode` to `symbol-sets upload` (also `POSTHOG_RELEASE_MODE`). `symbol-set`, the default, keeps binding the release to every uploaded symbol set. `event` uploads the symbol sets release-independent — bound to no release — so one symbol set serves every release of an unchanged binary and the upload needs no `--release-name`/`--release-version`. In event mode the release rides the event as `$release_id`, which the SDK reports from `POSTHOG_RELEASE_ID` (posthog-rs 0.26+); the release itself is named with `posthog-cli release resolve`, whose id you pass to the app.
