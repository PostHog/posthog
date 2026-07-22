---
cargo/posthog-cli: minor
---

`symbol-sets upload` now accepts standalone Mach-O executables and dylibs, not just ELF files and `.dSYM` bundles. Binaries that embed their own DWARF — Go binaries on macOS, which never produce a dSYM (`dsymutil` reports "no debug symbols in executable") — upload directly, with the `LC_UUID` as the symbol set id. Universal (fat) binaries upload one symbol set per architecture slice. Go's default darwin build compresses the embedded DWARF, which the server cannot read yet; such binaries are skipped with guidance to rebuild with `-ldflags=-compressdwarf=false`.
