---
cargo/posthog-cli: minor
---

Add `--release-mode` (env `POSTHOG_RELEASE_MODE`) to `inject`/`upload`/`process`. The default `symbol-set` keeps the existing behavior: the release id is stamped onto the uploaded symbol sets. The experimental `event` mode derives content-addressed chunk ids that stay stable across rebuilds and injects the release id into each JS chunk as `_posthogReleaseId`, so the SDK reports it per event and symbol sets stay release-independent. The release is still created; it just isn't bound to any chunk.
