---
cargo/posthog-cli: patch
---

In event release mode, `sourcemap upload` no longer uploads unchanged chunks again when the bundler names chunks by content, as Vite does by default. Every chunk carries the release id, so every release renamed every chunk, and the content hash covered those names: the map's `file`, the `sourceMappingURL` comment and imports of other chunks. The hash now leaves out the file names of the chunks in the upload. Hashes stored by earlier versions include the names, so the first upload after updating sends each chunk once more.
