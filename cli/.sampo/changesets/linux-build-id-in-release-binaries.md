---
cargo/posthog-cli: patch
---

Linux release binaries now embed a GNU build id, so native crash reports from the CLI can be matched to uploaded debug symbols.
