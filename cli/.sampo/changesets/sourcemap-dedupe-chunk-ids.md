---
cargo/posthog-cli: patch
---

Upload one symbol set per chunk id when processing sourcemaps. In `--release-mode event` a bundler that copies an entry point to a second name (a hashless alias beside `app-<hash>.js`) produces two byte-identical files that share a sourcemap, and so one content-addressed chunk id twice, which the bulk-start endpoint rejects as `invalid_chunk_ids`.
