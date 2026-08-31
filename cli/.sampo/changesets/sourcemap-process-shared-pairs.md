---
cargo/posthog-cli: patch
---

Fix a race in `sourcemap process`: the source pairs are now read from disk once, injected, and the same in-memory pairs are uploaded. Previously inject and upload each re-walked the directory roots, so a bundler writing into the scanned directory mid-run (e.g. Turbopack's background filesystem-cache flush on Next.js 16.3+) could hand the upload pass chunks the inject pass never stamped, aborting the whole run with "Chunk ID not found". That error now names the offending file and says how to recover. The "injecting selection" log line is bounded instead of printing every selected path, since a large stdin-provided selection used to produce a log line big enough to kill the CLI when stderr was a non-blocking pipe (e.g. spawned from Node.js).
