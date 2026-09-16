---
cargo/posthog-cli: patch
---

Stop reporting expected sourcemap upload outcomes as warnings. Missing releases and skipped empty sourcemaps now use lower log levels when uploads continue.
