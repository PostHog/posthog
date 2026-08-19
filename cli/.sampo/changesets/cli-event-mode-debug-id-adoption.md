---
cargo/posthog-cli: minor
---

With `--release-mode=event`, `sourcemap inject` now adopts a bundler-emitted ECMA-426 debug id (`//# debugId=` comment or the sourcemap's `debugId` field) as the chunk id instead of deriving its own, so one id identifies the chunk across the toolchain. The sourcemap's `debugId` field is preserved on save instead of being renamed to `chunk_id`, a bundler-stamped debug id no longer makes inject skip the mapping adjustment for the injected snippet, and hermes uploads still accept maps that carry only a `debugId`. Behavior change: `sourcemap upload --hermes` now fails with an error when it finds no maps carrying a chunk id or debug id, instead of exiting successfully having uploaded nothing.
