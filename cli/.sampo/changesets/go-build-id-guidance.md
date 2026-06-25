---
cargo/posthog-cli: patch
---

Mention Go's `-ldflags=-B=gobuildid` when `symbol-sets upload` finds ELF files without a GNU build id, since Go binaries don't emit one by default.
