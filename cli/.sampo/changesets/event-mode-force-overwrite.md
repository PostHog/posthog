---
cargo/posthog-cli: patch
---

Overwrite changed symbol sets by default in `--release-mode event`, and stop deriving a release-independent content hash for them. The injected snippet carries the release id, so re-running against an existing dist for a new release changed the uploaded bytes under an unchanged chunk id. That was previously papered over by hashing each pair with the injection undone; the upload now sends the hash of the bytes it uploads and overwrites on a mismatch. Pass `--skip-on-conflict` to keep the stored symbol set instead.
