---
cargo/posthog-cli: patch
---

Limit request diagnostics to metadata. Outside CI, API errors still show PostHog's error details and endpoint `--debug` still prints request and response bodies. In CI, both are hidden.
