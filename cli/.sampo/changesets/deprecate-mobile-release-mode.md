---
cargo/posthog-cli: minor
---

Deprecate `--release-mode` on `proguard upload` and `--no-release-bind` on `dsym upload`. Both flags are hidden no-ops now: each command uploads its symbol sets bound to the release it creates, which is what it did before the flags existed. A supplied flag prints a deprecation warning instead of changing the upload, so a released gradle plugin or upload-symbols.sh that still passes one keeps working. `proguard upload` no longer reads `POSTHOG_RELEASE_MODE`; the variable keeps steering `sourcemap inject`, `sourcemap process`, `sourcemap upload`, `hermes inject`, `hermes clone` and `hermes upload`.

Event mode pays off when two releases ship a byte-identical artifact. A proguard map id is a hash of the mapping, and a dSYM symbol set is keyed on the Mach-O `LC_UUID`, so an ordinary release that changes code already gets its own symbol set. The dSYM path also lost release attribution for embedded targets, because one upload covers every target's dSYM but creates one release.
