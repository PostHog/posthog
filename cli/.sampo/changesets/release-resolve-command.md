---
cargo/posthog-cli: minor
---

Add `posthog-cli release resolve`, which prints the id of the release the current build belongs to and creates the release if it doesn't exist yet. Only the id goes to stdout, so `RELEASE_ID=$(posthog-cli release resolve)` works; `--json` prints the whole release. It resolves the same release `sourcemap inject` would, so a bundler plugin that injects the release id into chunks itself lands on the same row. When nothing identifies a release, it prints nothing and exits `0`. `--dry-run` skips it, since resolving a release can create one.
