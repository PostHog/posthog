---
cargo/posthog-cli: minor
---

Remove `--release-mode` from `proguard upload` and `--no-release-bind` from `dsym upload`. Both commands upload their symbol sets bound to the release they create, which is what they did before those flags existed. `--release-mode` stays on `sourcemap inject`, `sourcemap process`, `sourcemap upload`, `hermes inject`, `hermes clone` and `hermes upload`.

Event mode pays off when two releases ship a byte-identical artifact. A proguard map id is a hash of the mapping, and a dSYM symbol set is keyed on the Mach-O `LC_UUID`, so an ordinary release that changes code already gets its own symbol set. The dSYM path also lost release attribution for embedded targets, because one upload covers every target's dSYM but creates one release. Both flags were experimental and undocumented.
