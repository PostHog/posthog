---
cargo/posthog-cli: patch
---

Ask the server which chunks it still needs before starting upload batches. A build whose chunks are mostly already uploaded now makes a few API calls instead of two per batch of 50.
