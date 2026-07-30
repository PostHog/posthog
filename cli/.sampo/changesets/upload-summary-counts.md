---
cargo/posthog-cli: patch
---

Sourcemap, dSYM, and ProGuard uploads now end with a single per-run summary line reporting how many chunks were uploaded, skipped as already present on the server, and skipped as too large. The summary is logged even when a run fails partway, and the same counts are attached to the `error_tracking_cli_sourcemaps_upload_finished` telemetry event so skip rates are queryable.
