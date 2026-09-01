---
cargo/posthog-cli: patch
---

Fix `--release-mode event` keeping a stale source map for a chunk that gains a release. The content hash ignored which snippet the chunk carried. The release snippet is longer than the chunk-id snippet, so it shifts the generated columns the uploaded map records. The two uploads therefore shared one hash, the server kept the first map, and later frames resolved to the wrong source positions. The hash now covers the snippet variant. It still ignores the release id itself, so a new release does not re-upload every chunk.
