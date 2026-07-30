---
cargo/posthog-cli: patch
---

Symbol set uploads (`sourcemap upload`, `sourcemap upload-hermes`, `symbol-sets upload`, dSYM and Proguard uploads) are now significantly faster: chunk uploads reuse a single HTTP connection pool instead of opening a fresh TLS connection per chunk, payload content hashes are computed once (in parallel) instead of twice per file, and sourcemap payload preparation (serialization + compression) runs across all cores.
