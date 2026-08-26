---
cargo/posthog-cli: minor
---

Add `--release-mode` to `symbol-sets upload`. `event` injects the created release's id into the binary — overwriting a fixed placeholder the SDK compiled in — so the SDK reports it as `$release_id`, the primary key the server resolves an exception's release from. The symbol sets upload release-independent, so a binary that did not change across two releases keeps one symbol set, and resolution no longer depends on the release name or version matching what the app reports. Injection is marker-driven and language-agnostic: it patches any native binary carrying the PostHog release marker (posthog-rs 0.26+) and no-ops elsewhere, leaving the build id untouched so symbols still match. `symbol-set` stays the default. On macOS the edit invalidates the Mach-O signature, so the CLI re-signs ad-hoc by default (and warns if it replaced a real identity); `--no-resign` skips that for pipelines that sign the binary themselves after upload.
