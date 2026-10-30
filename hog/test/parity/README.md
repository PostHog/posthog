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

## What is normalized

`normalize.ts` rewrites only values that are random by design:

- upload run and attempt IDs (UUIDv7)
- the key order of `content_hashes` and release `metadata`, which posthog-cli writes in hash-map order
- the order of object-storage uploads within one batch, which run in parallel
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

Regenerate them when posthog-cli changes what it uploads, and review the diff: a changed golden means hog and posthog-cli no longer agree until hog changes too.
