---
cargo/posthog-cli: patch
---

Derive the `--release-mode event` chunk id from the minified source alone, and overwrite a symbol set whose content changed instead of failing. Bundlers embed the original file in `sourcesContent`, so a comment-only edit rewrote the sourcemap and, with the map folded into the id, minted a new chunk for code that never changed. The content hash still covers source and map, so that edit re-uploads the chunk under its existing id. Chunk ids injected by earlier versions change once on the next build, which re-uploads those chunks under their new ids. `--skip-on-conflict` is now ignored in this mode, with a warning: every chunk carries the release id in its injected snippet, so every chunk conflicts on every release, and skipping them all would leave the previous release id in place.
