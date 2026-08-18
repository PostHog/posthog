---
cargo/posthog-cli: minor
---

Add `--release-mode` to `proguard upload`, matching `sourcemap upload`. `symbol-set` (the default) keeps stamping the release onto the uploaded mapping. EXPERIMENTAL `event` creates the release but leaves the mapping unbound, so each event resolves its own release from the app version and namespace the SDK already sends. A map id is derived from the mapping's own content, so this keeps one symbol set for a mapping that several releases share. Also settable via `POSTHOG_RELEASE_MODE`.
