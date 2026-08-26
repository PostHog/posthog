---
cargo/posthog-cli: minor
---

Add `--release-mode` to `hermes clone` and `hermes upload`. `event` leaves the uploaded Hermes source maps release-independent, so a React Native build that ships unchanged JavaScript across two releases keeps one symbol set instead of colliding on the release the first upload stamped on it. Each exception resolves its own release from the `$app_namespace` / `$app_version` / `$app_build` the SDK already sends, so pass `--release-name`, `--release-version` and `--build` matching the app's bundle identifier or applicationId, version and build number. `symbol-set` stays the default. `hermes inject --release-mode=event` no longer errors: it injects content-addressed chunk ids and, unlike a web build, embeds no release id, because a Hermes bytecode bundle has nothing to read one back out.
