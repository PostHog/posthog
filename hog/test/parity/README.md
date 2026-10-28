# Parity with posthog-cli

`hog error-tracking` must upload exactly what `posthog-cli` uploads.
PostHog stores a content hash per chunk ID, and a re-upload with a different hash fails with `content_hash_mismatch`.
So a byte that differs between the two CLIs breaks every customer who switches from one to the other.

These tests compare hog against goldens recorded from the Rust code.
The goldens are checked in, so the tests need no Rust toolchain.

## What is compared

| Test                 | Golden                                                            | Recorded with                                                           |
| -------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `containers.test.ts` | The content hash of a symbol set container, for 47 inputs         | `cli/examples/hog_parity_oracle.rs`, which calls posthog-cli's own code |
| `e2e.test.ts`        | Every request the CLI sends, the uploaded bytes and the exit code | The `posthog-cli` binary against `fake-server.ts`                       |

The container inputs sit on every boundary where libzstd's streaming output can differ from one-shot compression: exact multiples of the 128 KiB block, the 2 MiB window, and inputs up to 32 MiB.
`inputs.ts` generates them from a seed, so large inputs are never checked in.

The end-to-end scenarios cover a first upload, a re-upload of chunks PostHog already has, the multipart POST path, content and release conflicts with and without `--force` and `--skip-on-conflict`, check and start failures, and releases from flags and from git.

JavaScript scenarios also compare every file in the folder after the run, because `inject` rewrites bundles and maps, and `--delete-after` removes references and maps.
They run on real bundler output in `bundles/` (esbuild, rollup, webpack and terser, with and without native debug IDs) and on the edge cases in `js-fixtures.ts`.
Symbol-set mode mints random UUIDv7 chunk IDs, so `js-inject-symbol-set` compares where the IDs go, not their values.
The symbol-set upload scenarios then start from the files posthog-cli wrote in that scenario, so their content hashes are compared exactly.

Native scenarios compare `hog error-tracking upload` with `posthog-cli symbol-sets upload`, which takes ELF files, Mach-O files and dSYM bundles from one folder.
`native/build.sh` builds the binaries from the small C files in `native/src/` with Xcode's clang and ld.lld. Their DWARF records `/tmp/hog-parity-native` as the build folder.
The fixtures cover a fat dSYM, loose Mach-O DWARF files, files without debug info or a build ID, and two files that share a build ID.
The `--include-source` scenarios put `native/src/` back in that folder first with the `setup` hook, and one scenario leaves it empty to cover sources that can't be read.

The `release`, `extract` and `download` scenarios compare requests and the files each CLI writes. The fake server stores symbol sets for download, built with hog's writers, which the upload scenarios already hold to posthog-cli's bytes.

`real/` holds real Xcode, Rust and React Native output from getsentry/symbolic's test fixtures, with their MIT license. The `real-` scenarios run uploads, `--include-source`, `inject` and `clone` on them.

Hermes scenarios run the React Native steps in order with `before`: inject the Metro bundle, clone into the composed map, then upload.
The files in `hermes-fixtures.ts` are hand-written, with the Metro and Hermes keys, odd numbers and escapes that the serializer has to reproduce.

## What is normalized

`normalize.ts` rewrites only values that are random by design:

- upload run and attempt IDs (UUIDv7)
- the key order of `content_hashes` and release `metadata`, which posthog-cli writes in hash-map order
- the order of `symbol_sets` in request bodies, which follows posthog-cli's unsorted folder walk
- the order of object-storage uploads within one batch, which run in parallel
- random UUIDv7 chunk IDs in files, for scenarios marked `randomIds`

A golden lists only the files a run created, changed or deleted. Files over 2 KB are stored as their SHA-512, so goldens stay small and still catch every changed byte. A scenario that another one starts from sets `fullSnapshot` to keep whole files.

- the multipart boundary
- the user agent: hog sends `hog/<version>`, posthog-cli sends `posthog-cli`

Everything else is compared byte for byte, including the field order of every JSON body.

## Regenerate the goldens

Build both Rust binaries from `cli/`, then run the recorders from `hog/`:

```bash
(cd ../cli && cargo build --release && cargo build --release --example hog_parity_oracle)
TARGET=$(cd ../cli && cargo metadata --format-version 1 --no-deps | jq -r .target_directory)
bun test/parity/record-containers.ts "$TARGET/release/examples/hog_parity_oracle"
bun test/parity/record-e2e.ts "$TARGET/release/posthog-cli"
```

Record the JavaScript scenarios with a binary from the same `cli/` version, and keep one bundle per folder in new fixtures: posthog-cli's walk order decides which bundle wins a shared map or a duplicate chunk ID.

Regenerate them when posthog-cli changes what it uploads, and review the diff: a changed golden means hog and posthog-cli no longer agree until hog changes too.
