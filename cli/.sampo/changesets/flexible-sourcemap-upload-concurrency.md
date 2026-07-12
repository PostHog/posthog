---
cargo/posthog-cli: patch
---

Sourcemap upload concurrency can now be configured with `--concurrency` or `POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY`, while keeping the existing default of 10 uploads at a time.
