---
cargo/posthog-cli: minor
---

`symbol-sets upload` now also accepts Apple `.dSYM` bundles, packaging them through the same path as `dsym upload` (uppercase UUID chunk_ids, `AppleDsym` container). A single `posthog-cli symbol-sets upload --directory <dir>` run uploads both Linux ELF debug symbols and macOS dSYMs, so native symbol uploads no longer need a different command per platform. The dSYM branch shells out to `dwarfdump` (Xcode, macOS-only); when it is unavailable the bundle is reported and skipped while ELF symbols in the same directory still upload. The standalone `dsym upload` command is unchanged.
