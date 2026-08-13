---
cargo/posthog-cli: patch
---

Retry transient GitHub release download failures with exponential backoff when installing `@posthog/cli` from npm.
