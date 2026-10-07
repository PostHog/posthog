---
cargo/posthog-cli: patch
---

Upload native bundler debug IDs without rewriting source files through `--native-debug-ids`, and skip files without uploadable IDs instead of failing CI
