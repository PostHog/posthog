---
cargo/posthog-cli: patch
---

Retry symbol set uploads through the standard S3 endpoint when the transfer-acceleration endpoint is unreachable, so uploads complete on networks that block the accelerate domain. A 5 second connect timeout on uploads makes unreachable endpoints fail fast.
