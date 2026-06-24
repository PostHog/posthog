---
cargo/posthog-cli: patch
---

Add `symbol-sets upload` for native (ELF) debug symbols: it scans a directory for executables, shared libraries, and `objcopy --only-keep-debug` companions that carry a GNU build id and uploads them to PostHog.
