---
cargo/posthog-cli: minor
---

With `--no-release-bind`, `inject` now adopts a bundler-emitted ECMA-426 debug id (`//# debugId=` comment or the sourcemap's `debugId` field) as the chunk id instead of deriving its own, so one id identifies the chunk across the toolchain. The sourcemap's `debugId` field is preserved on save, and hermes uploads still accept maps that carry only a `debugId`.
