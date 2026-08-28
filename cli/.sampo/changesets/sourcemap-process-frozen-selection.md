---
cargo/posthog-cli: patch
---

Fix a race in `sourcemap process`: the file selection is now expanded into a concrete file list once and shared by the inject and upload passes. Previously each pass re-walked directory roots, so a bundler writing into the scanned directory mid-run (e.g. Turbopack's background filesystem-cache flush on Next.js 16.3+) could hand the upload pass chunks the inject pass never stamped, aborting the whole run with "Chunk ID not found". That error now also names the offending file.
