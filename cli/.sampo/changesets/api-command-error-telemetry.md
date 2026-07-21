---
cargo/posthog-cli: patch
---

`posthog-cli api` failures are now diagnosable and attributable. Launch failures report the specific cause (bundle not embedded in the build, no home directory, install-directory write failure with the underlying IO error kind, Node.js missing) both in the error message and in error telemetry, instead of one generic bundle-not-found error. When the proxied Node process fails, the CLI now exits through its normal path — flushing telemetry and honoring `--no-fail` — instead of terminating immediately, and the bundled API CLI flushes its own analytics before exiting non-zero so failed calls are no longer silently dropped. The `api` command also emits the standard command-run usage event and attaches the project id from `POSTHOG_CLI_PROJECT_ID`/`POSTHOG_CLI_ENV_ID` to telemetry when stored credentials are not used.
