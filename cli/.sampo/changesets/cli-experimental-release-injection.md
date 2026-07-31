---
cargo/posthog-cli: minor
---

Add experimental `--no-release-bind` (env `POSTHOG_NO_RELEASE_BIND`) to `inject`/`upload`/`process`: derive content-addressed chunk ids that stay stable across rebuilds, and inject the release id into each JS chunk as `_posthogReleaseId` so the SDK reports it per event, instead of stamping it onto the uploaded symbol sets. The release is still created — it just isn't bound to any chunk. Off by default; the existing paths are unchanged.
