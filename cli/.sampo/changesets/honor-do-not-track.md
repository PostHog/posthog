---
cargo/posthog-cli: patch
---

Honor `DO_NOT_TRACK`. When it is set to a value other than empty, `0` or `false`, the CLI sends no telemetry: no command, upload or exception events, and no panic capture.
